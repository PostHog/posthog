import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { teamLogic } from 'scenes/teamLogic'

import { todayRailStatusLogic } from '~/layout/today/todayRailStatusLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    EventsRetentionDeletionWarning,
    eventsRetentionDeletionWarningLogic,
} from './eventsRetentionDeletionWarningLogic'

const RETENTION = {
    project_retention_months: null,
    organization_retention_months: null,
    default_retention_months: 24,
    default_period_deletes: true,
    next_deletion_on: '2026-12-03',
}

const SCHEDULED_DELETION = { deletes_on: '2026-12-03', deletes_before: '2024-12-01', events_deleted: 1_200_000 }

const WARNING: EventsRetentionDeletionWarning = {
    title: 'Events older than 2\u00a0years will be deleted on Dec 3',
    description: "That's 1.2\u00a0M events in this project from before Dec 1, 2024.",
}

describe('eventsRetentionDeletionWarningLogic', () => {
    let retentionResponse: Record<string, unknown>
    let scheduledDeletionResponse: Record<string, unknown>
    let countRequests: number

    beforeEach(() => {
        countRequests = 0
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/events_retention/': () => [200, retentionResponse],
                '/api/projects/:team_id/events_retention/scheduled_deletion_count/': () => {
                    countRequests++
                    return [200, scheduledDeletionResponse]
                },
            },
        })
        initKeaTests()
    })

    function mountLogic(
        retention: Record<string, unknown>,
        scheduledDeletion: Record<string, unknown> = SCHEDULED_DELETION
    ): ReturnType<typeof eventsRetentionDeletionWarningLogic.build> {
        retentionResponse = retention
        scheduledDeletionResponse = scheduledDeletion
        const logic = eventsRetentionDeletionWarningLogic()
        logic.mount()
        return logic
    }

    it.each([
        ['warns before a default deletion', RETENTION, SCHEDULED_DELETION, WARNING, 1],
        [
            'counts a single event',
            RETENTION,
            { ...SCHEDULED_DELETION, events_deleted: 1 },
            { ...WARNING, description: "That's 1 event in this project from before Dec 1, 2024." },
            1,
        ],
        [
            'stays quiet when the deletion removes no events',
            RETENTION,
            { ...SCHEDULED_DELETION, events_deleted: 0 },
            null,
            1,
        ],
        [
            'skips a project with its own period',
            { ...RETENTION, project_retention_months: 12 },
            SCHEDULED_DELETION,
            null,
            0,
        ],
        [
            'skips a project under an organization period',
            { ...RETENTION, organization_retention_months: 12 },
            SCHEDULED_DELETION,
            null,
            0,
        ],
        [
            'skips a project the default period does not delete',
            { ...RETENTION, default_period_deletes: false },
            SCHEDULED_DELETION,
            null,
            0,
        ],
        [
            'skips a project with no deletion scheduled',
            { ...RETENTION, next_deletion_on: null },
            SCHEDULED_DELETION,
            null,
            0,
        ],
    ])('%s', async (_name, retention, scheduledDeletion, warning, expectedCountRequests) => {
        const logic = mountLogic(retention, scheduledDeletion)

        await expectLogic(logic).toDispatchActions(['loadRetentionSuccess']).toFinishAllListeners()

        expect(logic.values.warning).toEqual(warning)
        expect(logic.values.alertVisible).toBe(warning !== null)
        expect(countRequests).toBe(expectedCountRequests)
    })

    it('snoozes the alert for this project for a month and keeps the warning', async () => {
        const logic = mountLogic(RETENTION)
        await expectLogic(logic).toDispatchActions(['loadScheduledDeletionSuccess'])

        jest.useFakeTimers({ now: new Date('2026-11-12T12:00:00Z') })
        try {
            logic.actions.snooze()
        } finally {
            jest.useRealTimers()
        }

        expect(logic.values).toMatchObject({
            warning: WARNING,
            alertVisible: false,
            snoozedUntilByTeam: { [MOCK_DEFAULT_TEAM.id]: '2026-12-12T12:00:00.000Z' },
        })

        await expectLogic(logic, () => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 })
        }).toDispatchActions(['loadScheduledDeletionSuccess'])

        expect(logic.values.alertVisible).toBe(true)
    })

    it('marks the new navigation More menu until it opens', async () => {
        const logic = mountLogic(RETENTION)
        todayRailStatusLogic.mount()
        await expectLogic(logic).toDispatchActions(['loadScheduledDeletionSuccess'])
        expect(todayRailStatusLogic.values.moreSeverity).toBe('warning')
        expect(todayRailStatusLogic.values.moreLabel).toContain(WARNING.title)

        helpMenuLogic.actions.setHelpMenuOpen(true)

        expect(todayRailStatusLogic.values.moreSeverity).not.toBe('warning')
        expect(logic.values).toMatchObject({ warning: WARNING, alertVisible: false })
    })
})
