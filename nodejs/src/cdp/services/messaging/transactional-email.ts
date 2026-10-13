import { z } from 'zod'

import { HogFlow } from '~/cdp/schema/hogflow'

import { MessageTemplate } from './message-template-manager.service'

// The id of the email step in a transactional send's flow. It is signed into the tracking code as
// the action id, which is how engagement tracking tells a template send from a workflow send. The
// workflows API reserves it (graph_validation.py), so no workflow step can use it.
export const TRANSACTIONAL_EMAIL_ACTION_ID = 'transactional_email'

const TRIGGER_ACTION_ID = 'trigger_node'
const EXIT_ACTION_ID = 'exit_node'

// What a queued job stores. The worker loads the template content by id when it runs the job.
export const TransactionalEmailSourceSchema = z.object({
    template_id: z.string().min(1),
    to: z.string().email(),
    // The verified email sender integration that Django picked.
    from_integration_id: z.number().int().positive(),
})

export type TransactionalEmailSource = z.infer<typeof TransactionalEmailSourceSchema>

export const TransactionalEmailRequestSchema = TransactionalEmailSourceSchema.extend({
    // Attaches the engagement events to the person. The worker never loads the person.
    distinct_id: z.string().nullish(),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
})

export const isTransactionalEmailSend = (actionId: string | undefined | null): boolean =>
    actionId === TRANSACTIONAL_EMAIL_ACTION_ID

/**
 * A transactional send has no stored workflow. The workers run every email through a workflow, so
 * this builds a one-step flow (trigger, email, exit) in memory from the job state and the template.
 * The flow id is the message template id, which keys the send's metrics and logs to the template.
 */
export function buildTransactionalEmailFlow(
    teamId: number,
    source: TransactionalEmailSource,
    template: MessageTemplate
): HogFlow {
    const trigger: HogFlow['trigger'] = { type: 'manual', template_id: 'template-transactional-email', inputs: {} }
    const commonActionFields = { description: '', created_at: 0, updated_at: 0, filters: null }

    return {
        id: source.template_id,
        team_id: teamId,
        version: 1,
        name: template.name,
        status: 'active',
        trigger,
        exit_condition: 'exit_only_at_end',
        // Billed and quota limited as an email, like the email step of a workflow.
        billable_action_types: ['function_email'],
        actions: [
            { ...commonActionFields, id: TRIGGER_ACTION_ID, name: 'Trigger', type: 'trigger', config: trigger },
            {
                ...commonActionFields,
                id: TRANSACTIONAL_EMAIL_ACTION_ID,
                name: template.name,
                type: 'function_email',
                // The flow has nothing to continue to, so a failed send must fail the run.
                on_error: 'abort',
                config: {
                    message_category_id: template.message_category_id ?? undefined,
                    message_category_type: 'transactional',
                    template_uuid: source.template_id,
                    template_id: 'template-email',
                    inputs: {
                        email: {
                            value: {
                                to: { email: source.to, name: '' },
                                from: { integrationId: source.from_integration_id },
                                replyTo: '',
                                cc: '',
                                bcc: '',
                                subject: template.email.subject ?? '',
                                preheader: template.email.preheader ?? '',
                                text: template.email.text ?? '',
                                html: template.email.html ?? '',
                            },
                            templating: 'liquid',
                        },
                    },
                },
            },
            { ...commonActionFields, id: EXIT_ACTION_ID, name: 'Exit', type: 'exit', config: {} },
        ],
        edges: [
            { from: TRIGGER_ACTION_ID, to: TRANSACTIONAL_EMAIL_ACTION_ID, type: 'continue' },
            { from: TRANSACTIONAL_EMAIL_ACTION_ID, to: EXIT_ACTION_ID, type: 'continue' },
        ],
    }
}
