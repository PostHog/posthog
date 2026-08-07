import { expectLogic } from 'kea-test-utils'

import { isExternalLink } from 'lib/utils/url'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HealthCheckId } from './healthCheckTypes'
import { webAnalyticsHealthLogic } from './webAnalyticsHealthLogic'

function issue(kind: string, severity: 'critical' | 'warning'): Record<string, any> {
    return {
        id: `issue-${kind}`,
        kind,
        severity,
        status: 'active',
        dismissed: false,
        payload: {},
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        resolved_at: null,
    }
}

describe('webAnalyticsHealthLogic', () => {
    let logic: ReturnType<typeof webAnalyticsHealthLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:teamId/health_issues/': () => [
                    200,
                    {
                        count: 3,
                        results: [
                            issue('no_live_events', 'critical'),
                            issue('no_pageleave_events', 'warning'),
                            issue('scroll_depth', 'warning'),
                        ],
                    },
                ],
            },
        })
        initKeaTests()
        logic = webAnalyticsHealthLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The install CTAs used to point at an external docs URL, so the button only opened a
    // background tab and did nothing visible in the tab the user was looking at. They must
    // navigate to the in-app onboarding flow instead — an internal route, never targetBlank.
    it.each([HealthCheckId.PAGEVIEW_EVENTS, HealthCheckId.PAGELEAVE_EVENTS, HealthCheckId.SCROLL_DEPTH])(
        'routes the failing %s install CTA to the in-app onboarding flow, not external docs',
        async (checkId) => {
            await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

            const check = logic.values.allChecks.find((c) => c.id === checkId)
            expect(check?.status).not.toBe('success')
            expect(check?.action?.to).toContain('/onboarding')
            expect(isExternalLink(check?.action?.to)).toBe(false)
        }
    )
})
