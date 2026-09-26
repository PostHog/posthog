import { HogFunctionSubTemplateIdType } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATES, eventToHogFunctionContextId } from './sub-templates'

// The `key` of every entry in each destination template's inputs_schema. An input a sub-template
// writes under any other key is silently dropped, and the destination posts the template's default.
const DESTINATION_TEMPLATE_INPUT_KEYS: Record<string, string[]> = {
    // nodejs/src/cdp/templates/_destinations/slack/slack.template.ts
    'template-slack': ['slack_workspace', 'channel', 'icon_emoji', 'username', 'blocks', 'text', 'thread_ts'],
    // posthog/cdp/templates/discord/template_discord.py
    'template-discord': ['webhookUrl', 'content', 'allowedMentions'],
    // posthog/cdp/templates/microsoft_teams/template_microsoft_teams.py
    'template-microsoft-teams': ['webhookUrl', 'text'],
    // nodejs/src/cdp/templates/_destinations/webhook/webhook.template.ts
    'template-webhook': ['url', 'method', 'body', 'headers', 'signing_secret', 'debug'],
}

describe('sub-templates', () => {
    // One event per product that creates internal destinations. An id missing from the switch
    // falls back to 'standard', which merges that product into the notification list's "Other"
    // source and drops its source tag.
    it.each([
        ['$error_tracking_issue_created', 'error-tracking'],
        ['$insight_alert_firing', 'insight-alerts'],
        ['$experiment_metric_significant', 'experiment-alerts'],
        ['$activity_log_entry_created', 'activity-log'],
        ['$discussion_mention_created', 'discussion-mention'],
        ['$logs_alert_firing', 'logs-alerting'],
        ['$health_check_issue_firing', 'health-alerts'],
        ['$batch_export_run_failed', 'batch-export-alerts'],
        ['$feature_flag_stale', 'feature-flag-alerts'],
        ['$billing_alert_firing', 'billing-alerts'],
        ['$replay_vision_alert_match', 'replay-vision-alerts'],
        ['$pageview', 'standard'],
        [undefined, 'standard'],
    ])('reads %s as the %s context', (event, expected) => {
        expect(eventToHogFunctionContextId(event)).toBe(expected)
    })

    const chatSubTemplates: [HogFunctionSubTemplateIdType, string, string[]][] = (
        Object.keys(HOG_FUNCTION_SUB_TEMPLATES) as HogFunctionSubTemplateIdType[]
    ).flatMap((subTemplateId) =>
        HOG_FUNCTION_SUB_TEMPLATES[subTemplateId]
            .filter(
                (subTemplate) =>
                    subTemplate.template_id !== 'template-webhook' &&
                    subTemplate.template_id in DESTINATION_TEMPLATE_INPUT_KEYS
            )
            .map((subTemplate): [HogFunctionSubTemplateIdType, string, string[]] => [
                subTemplateId,
                subTemplate.template_id,
                Object.keys(subTemplate.inputs ?? {}),
            ])
    )

    // Webhook sub-templates are left out: several existing ones write `content`, a key the webhook
    // template does not have, and sorting those out is a change of its own.
    it.each(chatSubTemplates)('%s writes inputs its %s template reads', (_subTemplateId, templateId, inputKeys) => {
        expect(inputKeys.length).toBeGreaterThan(0)
        for (const key of inputKeys) {
            expect(DESTINATION_TEMPLATE_INPUT_KEYS[templateId]).toContain(key)
        }
    })
})
