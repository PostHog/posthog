// Mirrors the regex enforced by the Microsoft Teams hog template at
// posthog/cdp/templates/microsoft_teams/template_microsoft_teams.py. Keep in sync.
export const MICROSOFT_TEAMS_WEBHOOK_URL_REGEXES: RegExp[] = [
    /^https:\/\/[^/]+\.logic\.azure\.com:443\/workflows\/[^/]+\/triggers\/manual\/paths\/invoke?.*/,
    /^https:\/\/[^/]+\.webhook\.office\.com\/webhookb2\/[^/]+\/IncomingWebhook\/[^/]+\/[^/]+/,
    /^https:\/\/[^/]+\.powerautomate\.com\/[^/]+/,
    /^https:\/\/[^/]+\.flow\.microsoft\.com\/[^/]+/,
    /^https:\/\/[^/]+\.environment\.api\.powerplatform\.com(:443)?\/powerautomate\/automations\/direct\/workflows\/.*/,
]

export const MICROSOFT_TEAMS_WEBHOOK_URL_HELP =
    'Use one of: Azure Logic Apps (logic.azure.com), Power Platform webhook (webhook.office.com), Power Automate (powerautomate.com or flow.microsoft.com), or Power Platform environment (environment.api.powerplatform.com).'

export function validateTemplateInput(
    templateId: string | null | undefined,
    key: string,
    value: unknown
): string | null {
    if (!templateId) {
        return null
    }
    if (templateId === 'template-microsoft-teams' && key === 'webhookUrl') {
        if (typeof value !== 'string' || value.length === 0) {
            return null
        }
        if (!MICROSOFT_TEAMS_WEBHOOK_URL_REGEXES.some((r) => r.test(value))) {
            return `Invalid Microsoft Teams webhook URL. ${MICROSOFT_TEAMS_WEBHOOK_URL_HELP}`
        }
    }
    return null
}
