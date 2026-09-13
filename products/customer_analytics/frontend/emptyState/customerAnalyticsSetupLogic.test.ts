import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { customerAnalyticsSetupLogic, statusFromGroupsAccess } from './customerAnalyticsSetupLogic'

describe('customerAnalyticsSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        [GroupsAccessStatus.AlreadyUsing, 'has-data'],
        [GroupsAccessStatus.HasAccess, 'needs-setup'],
        [GroupsAccessStatus.HasGroupTypes, 'unknown'],
        [GroupsAccessStatus.NoAccess, 'unknown'],
        [GroupsAccessStatus.Hidden, 'unknown'],
    ] as const)('maps groups access %s to %s', (groupsAccessStatus, expected) => {
        expect(statusFromGroupsAccess(groupsAccessStatus)).toBe(expected)
    })

    // Detection only re-reported when the groups verdict changed value, so a team that
    // arrived (or changed) under an unchanged verdict left the answer stamped against the
    // earlier team. The gate reads that stale stamp as `loading` and covers the accounts
    // scene until the page is reloaded.
    it('re-stamps the status when the current team changes', async () => {
        const logic = customerAnalyticsSetupLogic()
        logic.mount()
        const setupLogic = productSetupStatusLogic({ productKey: ProductKey.CUSTOMER_ANALYTICS })
        const detectedStatus = setupLogic.values.status
        expect(detectedStatus).not.toBe('loading')

        const otherTeam = { ...teamLogic.values.currentTeam!, id: (teamLogic.values.currentTeamId ?? 0) + 1 }
        await expectLogic(logic, () => teamLogic.actions.loadCurrentTeamSuccess(otherTeam)).toFinishAllListeners()

        expect(setupLogic.values.status).toBe(detectedStatus)
    })
})
