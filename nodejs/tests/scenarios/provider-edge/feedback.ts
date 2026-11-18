import { createSign, randomUUID } from 'crypto'

import { internalFetch } from '~/common/utils/request'

import { Leaf } from './certificates'
import { SesMessage, addressesOf } from './ses'

export const SIGNING_CERT_PATH = '/SimpleNotificationService-scenarioedge.pem'

export type SnsSigner = { host: string; region: string; leaf: Leaf }

export type Bounce = { envelope: Record<string, string>; bouncedRecipients: string[] }

const SIGNATURE_VERSION_1_KEYS = ['Message', 'MessageId', 'Subject', 'Timestamp', 'TopicArn', 'Type']

function stringToSign(envelope: Record<string, string>): string {
    return SIGNATURE_VERSION_1_KEYS.filter((key) => envelope[key] !== undefined)
        .map((key) => `${key}\n${envelope[key]}\n`)
        .join('')
}

export function hardBounceOf(message: SesMessage, signer: SnsSigner): Bounce {
    const timestamp = new Date().toISOString()
    const bouncedRecipients = addressesOf([...message.to, ...(message.cc ?? []), ...(message.bcc ?? [])])
    const record = {
        eventType: 'Bounce',
        mail: {
            timestamp,
            source: message.from,
            messageId: message.messageId,
            destination: bouncedRecipients,
            headersTruncated: false,
            headers: Object.entries(message.headers).map(([name, value]) => ({ name, value })),
            commonHeaders: { from: [message.from], to: message.to, subject: message.subject },
            tags: {
                ...Object.fromEntries(Object.entries(message.tags).map(([name, value]) => [name, [value]])),
                ...(message.configurationSet ? { 'ses:configuration-set': [message.configurationSet] } : {}),
            },
        },
        bounce: {
            bounceType: 'Permanent',
            bounceSubType: 'General',
            bouncedRecipients: bouncedRecipients.map((emailAddress) => ({
                emailAddress,
                action: 'failed',
                status: '5.1.1',
                diagnosticCode: 'smtp; 550 5.1.1 user unknown',
            })),
            timestamp,
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
    return { envelope: { ...unsigned, Signature: signature }, bouncedRecipients }
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
