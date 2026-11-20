import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { healthSummaryLogic } from 'lib/components/HelpMenu/healthSummaryLogic'

import { initKeaTests } from '~/test/init'

import { healthSceneLogic } from './healthSceneLogic'

describe('healthSceneLogic', () => {
    let logic: ReturnType<typeof healthSceneLogic.build>
    let getSpy: jest.SpyInstance
    let createSpy: jest.SpyInstance
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getSpy = jest.spyOn(api, 'get').mockResolvedValue({ results: [], count: 0 })
        createSpy = jest.spyOn(api, 'create').mockResolvedValue({ scheduled_kinds: [], kinds_failed: [], team_id: 1 })
        updateSpy = jest.spyOn(api, 'update').mockResolvedValue({})
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads issues on mount without auto-firing the throttled refresh endpoint', async () => {
        logic = healthSceneLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        expect(getSpy).toHaveBeenCalled()
        // The refresh POST is throttled to one call per team every 5 minutes and checks re-run on a
        // daily schedule, so mounting must not auto-fire it — that was the source of the 429 storm.
        expect(createSpy).not.toHaveBeenCalled()
    })

    it('counts each category from the summary, not from the first page of issues', async () => {
        const issue = (id: string): Record<string, unknown> => ({
            id,
            kind: 'external_data_failure',
            severity: 'warning',
            payload: {},
            dismissed: false,
            snoozed_until: null,
        })
        getSpy.mockImplementation(async (url: string) =>
            url.includes('/summary/')
                ? {
                      unsnoozed: {
                          total: 417,
                          by_severity: { warning: 417 },
                          by_kind: { external_data_failure: 417 },
                          worst_severity_by_kind: { external_data_failure: 'warning' },
                      },
                      snoozed: {
                          total: 1,
                          by_severity: { critical: 1 },
                          by_kind: { sdk_outdated: 1 },
                          worst_severity_by_kind: { sdk_outdated: 'critical' },
                      },
                  }
                : { results: [issue('a'), issue('b')], count: 418 }
        )

        logic = healthSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])
        await expectLogic(healthSummaryLogic).toDispatchActions(['loadHealthSummarySuccess'])

        const byCategory = Object.fromEntries(logic.values.categorySummaries.map((s) => [s.category, s]))
        expect(byCategory.pipelines).toMatchObject({ issueCount: 417, worstSeverity: 'warning' })
        expect(byCategory.sdk).toMatchObject({ issueCount: 1, worstSeverity: 'critical' })
    })

    it('sends the snooze duration and refreshes the badge count', async () => {
        const summaryLogic = healthSummaryLogic()
        summaryLogic.mount()
        logic = healthSceneLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadHealthIssuesSuccess'])

        logic.actions.snoozeIssue('issue-1', '7d')

        // The badge reads the summary endpoint, so a snooze has to re-fetch it rather than wait
        // out healthSummaryLogic's five-minute refresh.
        await expectLogic(summaryLogic).toDispatchActions(['loadHealthSummary'])
        expect(updateSpy).toHaveBeenCalledWith(expect.stringContaining('health_issues/issue-1/'), {
            snoozed_until: '7d',
        })

        summaryLogic.unmount()
    })
})
