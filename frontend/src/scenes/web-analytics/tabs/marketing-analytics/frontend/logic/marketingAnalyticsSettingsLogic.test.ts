import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

describe('marketingAnalyticsSettingsLogic', () => {
    let logic: ReturnType<typeof marketingAnalyticsSettingsLogic.build>

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        logic = marketingAnalyticsSettingsLogic()
        logic.mount()
    })

    it('reverts an optimistic mapping when the server drops it on save', async () => {
        // Seed the optimistic config the settings UI shows right after the plus button.
        await expectLogic(logic, () => {
            logic.actions.loadMarketingAnalyticsConfigSuccess({
                sources_map: {},
                custom_source_mappings: { MetaAds: ['ig'] },
            })
        }).toMatchValues({
            marketingAnalyticsConfig: expect.objectContaining({ custom_source_mappings: { MetaAds: ['ig'] } }),
        })

        // The team PATCH comes back without the mapping (silently dropped server-side). Reconciling
        // against server truth must revert the optimistic value rather than leave a phantom tag.
        await expectLogic(logic, () => {
            teamLogic.actions.updateCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                marketing_analytics_config: { sources_map: {} },
            } as TeamType)
        }).toMatchValues({
            marketingAnalyticsConfig: { sources_map: {} },
        })
    })
})
