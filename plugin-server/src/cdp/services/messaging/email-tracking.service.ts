import crypto from 'crypto'
import { Counter } from 'prom-client'
import express from 'ultimate-express'

import { ModifiedRequest } from '~/api/router'
import { AppMetricType, CyclotronJobInvocationHogFunction, MinimalAppMetric } from '~/cdp/types'
import { defaultConfig } from '~/config/config'
import { captureException } from '~/utils/posthog'

import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { MailjetEventType, MailjetWebhookEvent } from './types'

export const PIXEL_GIF = Buffer.from('R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==', 'base64')
const LINK_REGEX =
    /<a\b[^>]*\bhref\s*=\s*(?:"(?!javascript:)([^"]*)"|'(?!javascript:)([^']*)'|(?!javascript:)([^'">\s]+))[^>]*>([\s\S]*?)<\/a>/gi

const EVENT_TYPE_TO_CATEGORY: Record<MailjetEventType, MinimalAppMetric['metric_name'] | undefined> = {
    sent: 'email_sent',
    open: 'email_opened',
    click: 'email_link_clicked',
    bounce: 'email_bounced',
    blocked: 'email_blocked',
    spam: 'email_spam',
    unsub: 'email_unsubscribed',
}

const trackingEventsCounter = new Counter({
    name: 'email_tracking_events_total',
    help: 'Total number of email tracking events received',
    labelNames: ['event_type', 'source'],
})

const emailTrackingErrorsCounter = new Counter({
    name: 'email_tracking_errors_total',
    help: 'Total number of email tracking processing errors',
    labelNames: ['error_type', 'source'],
})

export const parseEmailTrackingCode = (customId: string): { functionId: string; invocationId: string } | null => {
    // customId  is like ph_fn_id=function-1&ph_inv_id=invocation-1
    try {
        const params = new URLSearchParams(customId)
        const functionId = params.get('ph_fn_id')
        const invocationId = params.get('ph_inv_id')
        if (!functionId || !invocationId) {
            return null
        }
        return { functionId, invocationId }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>
): string => {
    return `ph_fn_id=${invocation.functionId}&ph_inv_id=${invocation.id}`
}

export const generateEmailTrackingPixelUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?${generateEmailTrackingCode(invocation)}`
}

export const generateTrackingRedirectUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>,
    targetUrl: string
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/redirect?${generateEmailTrackingCode(invocation)}&target=${encodeURIComponent(targetUrl)}`
}

export const addTrackingToEmail = (html: string, invocation: CyclotronJobInvocationHogFunction): string => {
    const trackingUrl = generateEmailTrackingPixelUrl(invocation)

    html = html.replace(LINK_REGEX, (m, d, s, u) => {
        const href = d || s || u || ''
        const tracked = generateTrackingRedirectUrl(invocation, href)

        // replace just the href in the original tag to preserve other attributes
        return m.replace(/\bhref\s*=\s*(?:"[^"]*"|'[^']*'|[^'">\s]+)/i, `href="${tracked}"`)
    })

    html = html.replace('</body>', `<img src="${trackingUrl}" style="display: none;" /></body>`)

    return html
}

export class EmailTrackingService {
    constructor(
        private hub: Hub,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService
    ) {}

    private async trackMetric({
        functionId,
        invocationId,
        metricName,
        source,
    }: {
        functionId?: string
        invocationId?: string
        metricName: MinimalAppMetric['metric_name']
        source: 'mailjet' | 'direct'
    }): Promise<void> {
        if (!functionId || !invocationId) {
            logger.error('[EmailTrackingService] trackMetric: Invalid custom ID', {
                functionId,
                invocationId,
                metricName,
            })
            emailTrackingErrorsCounter.inc({ error_type: 'invalid_custom_id', source })
            return
        }

        // The function ID could be one or the other so we load both
        const [hogFunction, hogFlow] = await Promise.all([
            this.hogFunctionManager.getHogFunction(functionId).catch(() => null),
            this.hogFlowManager.getHogFlow(functionId).catch(() => null),
        ])

        const teamId = hogFunction?.team_id ?? hogFlow?.team_id
        const appSourceId = hogFunction?.id ?? hogFlow?.id

        if (!teamId || !appSourceId) {
            logger.error('[EmailTrackingService] trackMetric: Hog function or flow not found', {
                functionId,
                invocationId,
                source,
            })
            emailTrackingErrorsCounter.inc({ error_type: 'hog_function_or_flow_not_found', source })
            return
        }

        this.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: teamId,
                app_source_id: appSourceId,
                instance_id: invocationId,
                metric_name: metricName,
                metric_kind: 'email',
                count: 1,
            },
            hogFlow ? 'hog_flow' : 'hog_function'
        )

        await this.hogFunctionMonitoringService.flush()

        trackingEventsCounter.inc({ event_type: metricName, source })
        logger.debug('[EmailTrackingService] trackMetric: Email tracking event', {
            functionId,
            invocationId,
            metricName,
        })
    }

    public async handleMailjetWebhook(
        req: ModifiedRequest
    ): Promise<{ status: number; message?: string; metrics?: AppMetricType[] }> {
        const signature = req.headers['x-mailjet-signature'] as string
        const timestamp = req.headers['x-mailjet-timestamp'] as string

        const okResponse = { status: 200, message: 'OK' }

        if (!signature || !timestamp || !req.rawBody) {
            return { status: 403, message: 'Missing required headers or body' }
        }

        const payload = `${timestamp}.${req.rawBody.toString()}`
        const hmac = crypto.createHmac('sha256', this.hub.MAILJET_SECRET_KEY).update(payload).digest()

        try {
            const signatureBuffer = Buffer.from(signature, 'hex')
            if (
                hmac.length !== signatureBuffer.length ||
                !crypto.timingSafeEqual(new Uint8Array(hmac), new Uint8Array(signatureBuffer))
            ) {
                emailTrackingErrorsCounter.inc({ error_type: 'invalid_signature' })
                logger.error('[EmailService] handleWebhook: Invalid signature', {
                    signature,
                    timestamp,
                    payload,
                })
                return { status: 403, message: 'Invalid signature' }
            }

            const event = req.body as MailjetWebhookEvent

            const { functionId, invocationId } = parseEmailTrackingCode(event.CustomID || '') || {}
            const category = EVENT_TYPE_TO_CATEGORY[event.event]

            if (!category) {
                logger.error('[EmailTrackingService] trackMetric: Unmapped event type', { event })
                emailTrackingErrorsCounter.inc({ error_type: 'unmapped_event_type' })
                return { status: 400, message: 'Unmapped event type' }
            }

            await this.trackMetric({
                functionId,
                invocationId,
                metricName: category,
                source: 'mailjet',
            })

            return okResponse
        } catch (error) {
            emailTrackingErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: Mailjet webhook error', { error })
            throw error
        }
    }

    public async handleEmailTrackingPixel(req: ModifiedRequest, res: express.Response): Promise<void> {
        // NOTE: this is somewhat naieve. We should expand with UA checking for things like apple's tracking prevention etc.
        const { ph_fn_id, ph_inv_id } = req.query

        // Track the value
        try {
            await this.trackMetric({
                functionId: ph_fn_id as string,
                invocationId: ph_inv_id as string,
                metricName: 'email_opened',
                source: 'direct',
            })
        } catch (error) {
            logger.error('[EmailTrackingService] handleEmailTrackingPixel: Error tracking open metric', { error })
            captureException(error)
        }

        res.status(200).set('Content-Type', 'image/gif').send(PIXEL_GIF)
    }

    public async handleEmailTrackingRedirect(req: ModifiedRequest, res: express.Response): Promise<void> {
        const { ph_fn_id, ph_inv_id, target } = req.query

        if (!target) {
            res.status(404).send('Not found')
            return
        }

        // Track the value
        try {
            await this.trackMetric({
                functionId: ph_fn_id as string,
                invocationId: ph_inv_id as string,
                metricName: 'email_link_clicked',
                source: 'direct',
            })
        } catch (error) {
            logger.error('[EmailTrackingService] handleEmailTrackingRedirect: Error tracking metric', { error })
            captureException(error)
        }

        res.redirect(target as string)
    }
}
