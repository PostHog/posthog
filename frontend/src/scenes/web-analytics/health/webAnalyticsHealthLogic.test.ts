import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HealthCheckId } from './healthCheckTypes'
import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

const issue = (payload: Record<string, any>): Record<string, any> => ({
    id: 'issue-1',
    kind: 'authorized_urls',
    severity: 'warning',
    status: 'active',
    dismissed: false,
    snoozed_until: null,
    payload,
    created_at: '2025-01-14T18:30:00Z',
    updated_at: '2025-01-14T18:30:00Z',
    resolved_at: null,
})

describe('webAnalyticsHealthLogic', () => {
    let logic: ReturnType<typeof webAnalyticsHealthLogic.build>

    const mountWithIssue = async (payload: Record<string, any>): Promise<string> => {
        useMocks({ get: { '/api/projects/:team_id/health_issues/': { results: [issue(payload)] } } })
        initKeaTests()
        logic = webAnalyticsHealthLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const check = logic.values.allChecks.find((c) => c.id === HealthCheckId.AUTHORIZED_URLS)
        return check?.description ?? ''
    }

    afterEach(() => logic?.unmount())

    it('tells a project that moved domains which host its pageviews come from', async () => {
        const description = await mountWithIssue({
            reason_code: 'domain_mismatch',
            unauthorized_hosts: [{ host: 'new.example.com', pageviews: 900 }],
        })

        expect(description).toContain('new.example.com')
        expect(description).toContain('moved to a new domain')
    })

    it('keeps the "nothing configured" copy when no authorized URLs are set', async () => {
        const description = await mountWithIssue({ reason_code: 'missing_urls' })

        expect(description).toContain('No authorized URLs configured')
    })
})
