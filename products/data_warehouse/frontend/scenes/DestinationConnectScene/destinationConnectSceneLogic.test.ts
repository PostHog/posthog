import { router } from 'kea-router'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'

describe('destinationConnectSceneLogic', () => {
    let unmountLogic: () => void

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        unmountLogic = destinationConnectSceneLogic.mount()
    })

    afterEach(() => {
        unmountLogic()
        jest.restoreAllMocks()
    })

    it.each([
        ['?kind=snowflake', 'Snowflake'],
        ['?kind=s3-compatible', 'S3'],
        ['?kind=twilio', null],
        ['', null],
    ])('resolves %s to destination type %s and tracks only a supported kind', (search, expectedType) => {
        router.actions.push(`/data-warehouse/connect-destination${search}`)

        expect(destinationConnectSceneLogic.values.destinationDefinition?.type ?? null).toEqual(expectedType)
        const viewed = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'warehouse destination connect page viewed'
        )
        expect(viewed).toHaveLength(expectedType ? 1 : 0)
    })

    it('keeps the saved connection when only the hash changes', () => {
        router.actions.push('/data-warehouse/connect-destination?kind=snowflake')
        destinationConnectSceneLogic.actions.setIntegrationId(42)

        router.actions.replace('/data-warehouse/connect-destination', { kind: 'snowflake' }, { panel: 'max' })

        expect(destinationConnectSceneLogic.values.integrationId).toEqual(42)
        const viewed = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'warehouse destination connect page viewed'
        )
        expect(viewed).toHaveLength(1)
    })
})
