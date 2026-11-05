import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
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

    it.each([
        { search: '?kind=snowflake&token=abc_123', status: 200, expected: 'sent', requested: true },
        { search: '?kind=snowflake&token=abc_123', status: 404, expected: 'failed', requested: true },
        { search: '?kind=snowflake', status: 200, expected: null, requested: false },
    ])(
        'hands the saved connection back for $search when the API returns $status',
        async ({ search, status, expected, requested }) => {
            const requests: unknown[] = []
            useMocks({
                post: {
                    '/api/projects/:team_id/external_data_destinations/connect_link_complete/': async ({ request }) => {
                        requests.push(await request.json())
                        return [status, {}]
                    },
                },
            })
            router.actions.push(`/data-warehouse/connect-destination${search}`)

            await expectLogic(destinationConnectSceneLogic, () => {
                destinationConnectSceneLogic.actions.setIntegrationId(42)
            }).toFinishAllListeners()

            expect(destinationConnectSceneLogic.values.handBackStatus).toEqual(expected)
            expect(requests).toEqual(requested ? [{ connect_token: 'abc_123', integration_id: 42 }] : [])
        }
    )
})
