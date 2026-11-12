import { expectLogic } from 'kea-test-utils'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'

import { eventsRetentionDeletionWarningLogic } from '~/layout/eventsRetentionDeletionWarningLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todayProjectMenuLogic } from './todayProjectMenuLogic'

describe('todayProjectMenuLogic', () => {
    it('clears the retention dot when the menu opens and keeps the retention row', async () => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/events_retention/': () => [
                    200,
                    {
                        project_retention_months: null,
                        organization_retention_months: null,
                        default_retention_months: 24,
                        default_period_deletes: true,
                        next_deletion_on: '2026-12-03',
                    },
                ],
                '/api/projects/:team_id/events_retention/scheduled_deletion_count/': () => [
                    200,
                    { deletes_on: '2026-12-03', deletes_before: '2024-12-01', events_deleted: 5 },
                ],
            },
        })
        initKeaTests()
        const logic = todayProjectMenuLogic()
        logic.mount()
        await expectLogic(eventsRetentionDeletionWarningLogic).toDispatchActions(['loadScheduledDeletionSuccess'])
        expect(eventsRetentionDeletionWarningLogic.values.alertVisible).toBe(true)

        newAccountMenuLogic.actions.openProjectSwitcher()

        expect(eventsRetentionDeletionWarningLogic.values.alertVisible).toBe(false)
        expect(logic.values.projectMenuActions.map(({ key }) => key)).toContain('events-retention')
    })
})
