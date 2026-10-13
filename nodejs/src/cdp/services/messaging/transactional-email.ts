import { z } from 'zod'

import { HogFlow } from '~/cdp/schema/hogflow'

// The id of the email step in a transactional send's flow. It is signed into the tracking code as
// the action id, which is how engagement tracking tells a template send from a workflow send. The
// workflows API reserves it (graph_validation.py), so no workflow step can use it.
export const TRANSACTIONAL_EMAIL_ACTION_ID = 'transactional_email'

const TRIGGER_ACTION_ID = 'trigger_node'
const EXIT_ACTION_ID = 'exit_node'

export const TransactionalEmailSourceSchema = z.object({
    template_id: z.string().min(1),
    template_name: z.string(),
    message_category_id: z.string().nullish(),
    // The `native_email` input value, built by Django from the template content, the recipient and the sender.
    email: z.record(z.string(), z.any()),
})

export type TransactionalEmailSource = z.infer<typeof TransactionalEmailSourceSchema>

export const TransactionalEmailRequestSchema = TransactionalEmailSourceSchema.extend({
    // Attaches the engagement events to the person, and makes their properties available to the template.
    distinct_id: z.string().nullish(),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
})

export const isTransactionalEmailSend = (actionId: string | undefined | null): boolean =>
    actionId === TRANSACTIONAL_EMAIL_ACTION_ID

/**
 * A transactional send has no stored workflow. The workers run every email through a workflow, so
 * this builds a one-step flow (trigger, email, exit) in memory from the job state. The flow id is
 * the message template id, which keys the send's metrics and logs to the template.
 */
export function buildTransactionalEmailFlow(teamId: number, source: TransactionalEmailSource): HogFlow {
    const trigger: HogFlow['trigger'] = { type: 'manual', template_id: 'template-transactional-email', inputs: {} }
    const commonActionFields = { description: '', created_at: 0, updated_at: 0, filters: null }

    return {
        id: source.template_id,
        team_id: teamId,
        version: 1,
        name: source.template_name,
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
                name: source.template_name,
                type: 'function_email',
                // The flow has nothing to continue to, so a failed send must fail the run.
                on_error: 'abort',
                config: {
                    message_category_id: source.message_category_id ?? undefined,
                    message_category_type: 'transactional',
                    template_uuid: source.template_id,
                    template_id: 'template-email',
                    inputs: { email: { value: source.email, templating: 'liquid' } },
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
