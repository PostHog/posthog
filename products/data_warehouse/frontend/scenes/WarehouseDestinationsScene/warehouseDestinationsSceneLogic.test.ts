import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { warehouseDestinationsSceneLogic } from './warehouseDestinationsSceneLogic'

const REDSHIFT = {
    id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    type: 'Redshift',
    name: 'Redshift',
    config: { database: 'analytics', schema: 'raw' },
    integration: 1,
    is_posthog_warehouse: false,
    status: 'failing',
    latest_error: 'PostHog could not deliver data to this destination. The next sync will try again.',
    latest_error_at: '2026-11-17T09:00:00Z',
    synced_sources: [],
} as unknown as ExternalDataDestinationApi

describe('warehouseDestinationsSceneLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/external_data_destinations/': { results: [REDSHIFT] },
                '/api/projects/:team_id/external_data_sources/': { results: [] },
            },
        })
        initKeaTests()
        warehouseDestinationsSceneLogic.mount()
    })

    test.each([
        ['a destination link opens that destination', urls.warehouseDestination(REDSHIFT.id), REDSHIFT.id, REDSHIFT],
        ['an unknown id opens nothing', urls.warehouseDestination('missing'), 'missing', null],
        ['the plain list selects nothing', urls.warehouseDestinations(), null, null],
    ])('%s', async (_name, url, expectedId, expectedDestination) => {
        await expectLogic(warehouseDestinationsSceneLogic, () => router.actions.push(url)).toDispatchActions([
            'loadDestinationsSuccess',
        ])

        expect(warehouseDestinationsSceneLogic.values.selectedDestinationId).toEqual(expectedId)
        expect(warehouseDestinationsSceneLogic.values.selectedDestination).toEqual(expectedDestination)
    })

    test('going back to the list clears the selected destination', async () => {
        await expectLogic(warehouseDestinationsSceneLogic, () =>
            router.actions.push(urls.warehouseDestination(REDSHIFT.id))
        ).toDispatchActions(['loadDestinationsSuccess'])
        expect(warehouseDestinationsSceneLogic.values.selectedDestination).toEqual(REDSHIFT)

        router.actions.push(urls.warehouseDestinations())

        expect(warehouseDestinationsSceneLogic.values.selectedDestinationId).toBeNull()
        expect(warehouseDestinationsSceneLogic.values.selectedDestination).toBeNull()
    })
})
