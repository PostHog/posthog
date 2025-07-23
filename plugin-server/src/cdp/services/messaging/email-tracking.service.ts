import crypto from 'crypto'
import { Counter } from 'prom-client'

import { AppMetricType, CyclotronJobInvocationHogFunction, MinimalAppMetric } from '~/cdp/types'
import { ModifiedRequest } from '~/router'

import { Hub } from '../../../types'
import { logger } from '../../../utils/logger'
import { HogFlowManagerService } from '../hogflows/hogflow-manager.service'
import { HogFunctionManagerService } from '../managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { MailjetEventType, MailjetWebhookEvent } from './types'

const EVENT_TYPE_TO_CATEGORY: Record<MailjetEventType, MinimalAppMetric['metric_name'] | undefined> = {
    sent: 'email_sent',
    open: 'email_opened',
    click: 'email_clicked',
    bounce: 'email_bounced',
    blocked: 'email_blocked',
    spam: 'email_spam',
    unsub: 'email_unsubscribed',
}

const mailjetWebhookEventsCounter = new Counter({
    name: 'mailjet_webhook_events_total',
    help: 'Total number of Mailjet webhook events received',
    labelNames: ['event_type'],
})

const mailjetWebhookErrorsCounter = new Counter({
    name: 'mailjet_webhook_errors_total',
    help: 'Total number of Mailjet webhook processing errors',
    labelNames: ['error_type'],
})

export const parseMailjetCustomId = (customId: string): { functionId: string; invocationId: string } | null => {
    // customId  is like ph_fn_id=function-1&ph_inv_id=invocation-1
    try {
        const params = new URLSearchParams(customId)
        const functionId = params.get('ph_fn_id')
        const invocationId = params.get('ph_inv_id')
        if (!functionId || !invocationId) {
            return null
        }
        return { functionId, invocationId }
    } catch (error) {
        return null
    }
}

export const generateMailjetCustomId = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>
): string => {
    return `ph_fn_id=${invocation.functionId}&ph_inv_id=${invocation.id}`
}

export class EmailTrackingService {
    constructor(
        private hub: Hub,
        private hogFunctionManager: HogFunctionManagerService,
        private hogFlowManager: HogFlowManagerService,
        private hogFunctionMonitoringService: HogFunctionMonitoringService
    ) {}

    private async trackMetric(event: MailjetWebhookEvent): Promise<void> {
        const { functionId, invocationId } = parseMailjetCustomId(event.CustomID || '') || {}
        const category = EVENT_TYPE_TO_CATEGORY[event.event]

        if (!functionId || !invocationId) {
            logger.error('[EmailTrackingService] trackMetric: Invalid custom ID', { event })
            mailjetWebhookErrorsCounter.inc({ error_type: 'invalid_custom_id' })
            return
        }

        if (!category) {
            logger.error('[EmailTrackingService] trackMetric: Unmapped event type', { event })
            mailjetWebhookErrorsCounter.inc({ error_type: 'unmapped_event_type' })
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
            })
            mailjetWebhookErrorsCounter.inc({ error_type: 'hog_function_or_flow_not_found' })
            return
        }

        this.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: teamId,
                app_source_id: appSourceId,
                instance_id: invocationId,
                metric_name: category,
                metric_kind: 'email',
                count: 1,
            },
            hogFlow ? 'hog_flow' : 'hog_function'
        )

        await this.hogFunctionMonitoringService.produceQueuedMessages()

        mailjetWebhookEventsCounter.inc({ event_type: category })
        logger.debug('[EmailTrackingService] trackMetric: Mailjet webhook event', { event })
    }

    public async handleWebhook(
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
                mailjetWebhookErrorsCounter.inc({ error_type: 'invalid_signature' })
                logger.error('[EmailService] handleWebhook: Invalid signature', {
                    signature,
                    timestamp,
                    payload,
                })
                return { status: 403, message: 'Invalid signature' }
            }

            const event = req.body as MailjetWebhookEvent

            await this.trackMetric(event)

            // TODO: Move this function to a dedicated email webhook service - makes more sense...
            // NOTE: Here we need to try and load the fn or flow for the ID to track the metric for it...
            return okResponse
        } catch (error) {
            mailjetWebhookErrorsCounter.inc({ error_type: error.name || 'unknown' })
            logger.error('[EmailService] handleWebhook: Mailjet webhook error', { error })
            throw error
        }
    }
}
