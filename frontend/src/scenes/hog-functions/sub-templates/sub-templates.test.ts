import { HOG_FUNCTION_SUB_TEMPLATES } from './sub-templates'

const FINGERPRINT_PATH_SEGMENT = '{encodeURLComponent(event.properties.fingerprint)}'
const FINGERPRINT_PATH_EXPRESSION = 'encodeURLComponent(event.properties.fingerprint'
const ERROR_TRACKING_ALERT_SUB_TEMPLATE_IDS = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
] as const
const EXTERNAL_ISSUE_TEMPLATE_IDS = ['template-linear', 'template-github', 'template-gitlab'] as const

describe('error tracking alert sub-templates', () => {
    it.each(ERROR_TRACKING_ALERT_SUB_TEMPLATE_IDS)('%s uses fingerprint-based issue links', (subTemplateId) => {
        const serializedTemplates = JSON.stringify(HOG_FUNCTION_SUB_TEMPLATES[subTemplateId])
        const issueUrls = serializedTemplates.match(/\{project\.url\}\/error_tracking\/[^"\\)\s]+/g) ?? []

        expect(issueUrls.length).toBeGreaterThan(0)
        expect(issueUrls.every((url) => url.includes(FINGERPRINT_PATH_EXPRESSION))).toBe(true)
        expect(serializedTemplates).not.toContain('/error_tracking/{event.distinct_id}')
    })

    it.each(EXTERNAL_ISSUE_TEMPLATE_IDS)('%s receives the encoded fingerprint as its issue path', (templateId) => {
        const template = HOG_FUNCTION_SUB_TEMPLATES['error-tracking-issue-created'].find(
            (candidate) => candidate.template_id === templateId
        )

        expect(template?.inputs?.posthog_issue_id?.value).toBe(FINGERPRINT_PATH_SEGMENT)
    })
})
