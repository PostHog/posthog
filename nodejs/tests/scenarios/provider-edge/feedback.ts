import { createSign, randomUUID } from 'crypto'
import { z } from 'zod'

import { internalFetch } from '~/common/utils/request'

import { Leaf } from './certificates'
import { SesMessage, addressesOf } from './ses'

export const SIGNING_CERT_PATH = '/SimpleNotificationService-scenarioedge.pem'

export type SnsSigner = { host: string; region: string; leaf: Leaf }

const SIGNATURE_VERSION_1_KEYS = ['Message', 'MessageId', 'Subject', 'Timestamp', 'TopicArn', 'Type']

function stringToSign(envelope: Record<string, string>): string {
    return SIGNATURE_VERSION_1_KEYS.filter((key) => envelope[key] !== undefined)
        .map((key) => `${key}\n${envelope[key]}\n`)
        .join('')
}

export const SHARE_TOLERANCE = 1e-9

const Share = z.number().min(0).max(1).default(0)

export const FeedbackShares = z
    .object({
        delivery: Share,
        hardBounce: Share,
        softBounce: Share,
        complaint: Share,
        open: Share,
        click: Share,
    })
    .strict()
    .refine(
        ({ delivery, hardBounce, softBounce }) => delivery + hardBounce + softBounce <= 1 + SHARE_TOLERANCE,
        'delivery and bounces add up to more than 1'
    )
    .refine(({ delivery, complaint }) => complaint <= delivery, 'complaint is more than delivery')
    .refine(({ delivery, open }) => open <= delivery, 'open is more than delivery')
    .refine(({ open, click }) => click <= open, 'click is more than open')
export type FeedbackShares = z.infer<typeof FeedbackShares>

export type FeedbackEvent = keyof FeedbackShares

type Outcome = 'delivery' | 'hardBounce' | 'softBounce' | 'none'

const crossed = (count: number, share: number): boolean =>
    Math.floor(count * share + SHARE_TOLERANCE) > Math.floor((count - 1) * share + SHARE_TOLERANCE)

const shareOf = (part: number, whole: number): number => (whole === 0 ? 0 : part / whole)

export class FeedbackPlan {
    private readonly weights: Record<Outcome, number>
    private readonly credit: Record<Outcome, number> = { delivery: 0, hardBounce: 0, softBounce: 0, none: 0 }
    private delivered = 0
    private opened = 0

    constructor(private readonly shares: FeedbackShares) {
        const { delivery, hardBounce, softBounce } = shares
        this.weights = { delivery, hardBounce, softBounce, none: Math.max(0, 1 - delivery - hardBounce - softBounce) }
    }

    eventsOfNextSend(tracksEngagement: boolean): FeedbackEvent[] {
        const outcome = this.nextOutcome()
        if (outcome !== 'delivery') {
            return outcome === 'none' ? [] : [outcome]
        }
        const { delivery, open, click, complaint } = this.shares
        const events: FeedbackEvent[] = ['delivery']
        this.delivered += 1
        if (tracksEngagement && crossed(this.delivered, shareOf(open, delivery))) {
            this.opened += 1
            events.push('open')
            if (crossed(this.opened, shareOf(click, open))) {
                events.push('click')
            }
        }
        if (crossed(this.delivered, shareOf(complaint, delivery))) {
            events.push('complaint')
        }
        return events
    }

    private nextOutcome(): Outcome {
        const outcomes = Object.keys(this.weights) as Outcome[]
        for (const outcome of outcomes) {
            this.credit[outcome] += this.weights[outcome]
        }
        const next = outcomes.reduce((best, outcome) => (this.credit[outcome] > this.credit[best] ? outcome : best))
        this.credit[next] -= 1
        return next
    }
}

export type Notification = { envelope: Record<string, string>; eventType: string; bouncedRecipients?: string[] }

const BOUNCES = {
    hardBounce: { bounceType: 'Permanent', status: '5.1.1', diagnosticCode: 'smtp; 550 5.1.1 user unknown' },
    softBounce: { bounceType: 'Transient', status: '4.2.2', diagnosticCode: 'smtp; 452 4.2.2 mailbox full' },
}

const OPENED_BY = { ipAddress: '192.0.2.1', userAgent: 'Scenario mail client' }

type SesEvent = { eventType: string } & Record<string, unknown>

function eventOf(event: FeedbackEvent, recipients: string[], timestamp: string): SesEvent {
    switch (event) {
        case 'delivery':
            return {
                eventType: 'Delivery',
                delivery: { timestamp, recipients, processingTimeMillis: 0, smtpResponse: '250 2.0.0 OK' },
            }
        case 'hardBounce':
        case 'softBounce': {
            const { bounceType, status, diagnosticCode } = BOUNCES[event]
            return {
                eventType: 'Bounce',
                bounce: {
                    bounceType,
                    bounceSubType: 'General',
                    bouncedRecipients: recipients.map((emailAddress) => ({
                        emailAddress,
                        action: 'failed',
                        status,
                        diagnosticCode,
                    })),
                    timestamp,
                },
            }
        }
        case 'complaint':
            return {
                eventType: 'Complaint',
                complaint: {
                    complainedRecipients: recipients.map((emailAddress) => ({ emailAddress })),
                    complaintFeedbackType: 'abuse',
                    feedbackId: randomUUID(),
                    timestamp,
                },
            }
        case 'open':
            return { eventType: 'Open', open: { ...OPENED_BY, timestamp } }
        case 'click':
            return { eventType: 'Click', click: { ...OPENED_BY, link: 'https://www.example.com/', timestamp } }
    }
}

export function notificationOf(message: SesMessage, event: FeedbackEvent, signer: SnsSigner): Notification {
    const timestamp = new Date().toISOString()
    const recipients = addressesOf([...message.to, ...(message.cc ?? []), ...(message.bcc ?? [])])
    const record = {
        ...eventOf(event, recipients, timestamp),
        mail: {
            timestamp,
            source: message.from,
            messageId: message.messageId,
            destination: recipients,
            headersTruncated: false,
            headers: Object.entries(message.headers).map(([name, value]) => ({ name, value })),
            commonHeaders: { from: [message.from], to: message.to, subject: message.subject },
            tags: {
                ...Object.fromEntries(Object.entries(message.tags).map(([name, value]) => [name, [value]])),
                ...(message.configurationSet ? { 'ses:configuration-set': [message.configurationSet] } : {}),
            },
        },
    }
    const unsigned: Record<string, string> = {
        Type: 'Notification',
        MessageId: randomUUID(),
        TopicArn: `arn:aws:sns:${signer.region}:000000000000:scenario-ses-feedback`,
        Message: JSON.stringify(record),
        Timestamp: timestamp,
        SignatureVersion: '1',
        SigningCertURL: `https://${signer.host}${SIGNING_CERT_PATH}`,
    }
    const signature = createSign('RSA-SHA1').update(stringToSign(unsigned)).sign(signer.leaf.key, 'base64')
    return {
        envelope: { ...unsigned, Signature: signature },
        eventType: record.eventType,
        ...(event === 'hardBounce' || event === 'softBounce' ? { bouncedRecipients: recipients } : {}),
    }
}

export async function postFeedback(
    url: string,
    envelope: Record<string, string>
): Promise<{ status: number; error?: string }> {
    try {
        const response = await internalFetch(url, {
            method: 'POST',
            headers: {
                'content-type': 'text/plain; charset=UTF-8',
                'x-amz-sns-message-type': envelope.Type,
                'x-amz-sns-topic-arn': envelope.TopicArn,
            },
            body: JSON.stringify(envelope),
        })
        const body = await response.text()
        return response.status >= 200 && response.status < 300
            ? { status: response.status }
            : { status: response.status, error: body }
    } catch (error) {
        return { status: 0, error: String(error) }
    }
}
