import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { connectionSelectorLogic, POSTHOG_WAREHOUSE } from './connectionSelectorLogic'

describe('connectionSelectorLogic', () => {
    let logic: ReturnType<typeof connectionSelectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(api.externalDataSources, 'connections').mockResolvedValue([
            {
                id: 'conn-123',
                prefix: 'warehouse',
                engine: 'postgres',
            },
        ] as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('loads connection options on mount when direct query is enabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
        })

        logic = connectionSelectorLogic({ selectedConnectionId: undefined })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(api.externalDataSources.connections).toHaveBeenCalledTimes(1)
        expect(logic.values.connectionSelectorValue).toEqual(POSTHOG_WAREHOUSE)
        expect(logic.values.connectionSelectOptions[0].options).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ value: POSTHOG_WAREHOUSE }),
                expect.objectContaining({ value: 'conn-123', label: 'warehouse (Postgres)' }),
            ])
        )
    })
})
