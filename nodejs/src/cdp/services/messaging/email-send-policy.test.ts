import { IntegrationType } from '~/cdp/types'

import { EmailSendingSuspensionCause } from '../managers/team-workflows-config.service'
import { EmailSendPolicy, SendCandidate } from './email-send-policy'

const TEAM_ID = 2

const verifiedSender = (overrides: Partial<IntegrationType> = {}): IntegrationType => ({
    id: 1,
    team_id: TEAM_ID,
    kind: 'email',
    config: { email: 'hello@example.com', name: 'Example', domain: 'example.com', verified: true },
    sensitive_config: {},
    ...overrides,
})

const candidate = (overrides: Partial<SendCandidate> = {}): SendCandidate => ({
    teamId: TEAM_ID,
    workflowMetadata: {},
    sender: verifiedSender(),
    recipients: ['jane@example.com'],
    ...overrides,
})

const policyWith = ({
    suspension = null,
    suppressed = [],
}: { suspension?: EmailSendingSuspensionCause | null; suppressed?: string[] } = {}): EmailSendPolicy =>
    new EmailSendPolicy(
        { getEmailSendingSuspension: () => Promise.resolve(suspension) },
        { isSuppressed: (_teamId: number, email: string) => Promise.resolve(suppressed.includes(email)) }
    )

describe('EmailSendPolicy', () => {
    it('passes a send every check allows', async () => {
        expect(await policyWith().check(candidate())).toEqual({ ok: true, sender: verifiedSender() })
    })

    it.each([
        ['staff', 'Email sending is suspended for this project. Contact support to get sending re-enabled.'],
        [
            'provider',
            'Our email provider paused sending for this project. Check the Reputation tab to see what to fix.',
        ],
    ] as const)('rejects a send while the team is suspended by %s', async (cause, detail) => {
        const decision = await policyWith({ suspension: cause }).check(candidate())

        expect(decision).toMatchObject({ ok: false, code: 'sending_suspended', detail })
        expect(decision).toHaveProperty('why', expect.any(String))
        expect(decision).toHaveProperty('fix', expect.any(String))
    })

    it.each([
        [
            'a pause for complaints',
            { email_sending_paused_reason: 'Spam complaints reached 2% of the 400 emails sent.' },
            'Email sending is paused for this workflow. Spam complaints reached 2% of the 400 emails sent. Resume it from the workflow page once the audience is cleaned up.',
        ],
        [
            'a staff pause',
            { email_sending_paused_reason: 'Paused by staff.', email_sending_paused_by: 'staff' },
            'PostHog staff paused email sending for this workflow. Paused by staff. Contact support to get sending re-enabled.',
        ],
    ])('rejects a send while its workflow has %s', async (_name, pause, detail) => {
        const decision = await policyWith().check(
            candidate({ workflowMetadata: { email_sending_paused_at: '2026-01-01T00:00:00Z', ...pause } })
        )

        expect(decision).toMatchObject({ ok: false, code: 'template_paused', detail })
    })

    it.each([
        [
            'is missing',
            null,
            "Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step.",
        ],
        [
            'belongs to another team',
            verifiedSender({ team_id: TEAM_ID + 1 }),
            "Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step.",
        ],
        [
            'is not an email channel',
            verifiedSender({ kind: 'slack' }),
            "The integration configured for this step is not an email channel — select an email sender in the workflow's email step.",
        ],
        [
            'is on an unverified domain',
            verifiedSender({ config: { email: 'hello@example.com', name: 'Example', verified: false } }),
            'The selected email integration domain is not verified',
        ],
        [
            'has no address or name',
            verifiedSender({ config: { email: 'hello@example.com', verified: true } }),
            'The selected email integration is not configured correctly',
        ],
    ])('rejects a send whose sender %s', async (_name, sender, detail) => {
        const decision = await policyWith().check(candidate({ sender }))

        expect(decision).toMatchObject({ ok: false, code: 'sender_not_verified', detail })
    })

    it('rejects a send with any suppressed recipient and names each one', async () => {
        const decision = await policyWith({ suppressed: ['cc@example.com', 'bcc@example.com'] }).check(
            candidate({ recipients: ['jane@example.com', 'cc@example.com', 'bcc@example.com'] })
        )

        expect(decision).toMatchObject({
            ok: false,
            code: 'recipient_suppressed',
            detail: 'Recipient(s) on the suppression list: cc@example.com, bcc@example.com',
        })
    })

    it('reports a suspension before a pause, a pause before the sender, and the sender before suppression', async () => {
        const everythingFails = candidate({
            workflowMetadata: { email_sending_paused_at: '2026-01-01T00:00:00Z' },
            sender: null,
        })
        const policy = policyWith({ suspension: 'staff', suppressed: ['jane@example.com'] })

        expect(await policy.check(everythingFails)).toMatchObject({ code: 'sending_suspended' })
        expect(await policyWith({ suppressed: ['jane@example.com'] }).check(everythingFails)).toMatchObject({
            code: 'template_paused',
        })
        expect(await policyWith({ suppressed: ['jane@example.com'] }).check(candidate({ sender: null }))).toMatchObject(
            { code: 'sender_not_verified' }
        )
    })
})
