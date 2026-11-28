import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getPropertyDisplayInfo, playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, SessionRecordingType } from '~/types'

import recordingEventsJson from '../../__mocks__/recording_events_query'
import { recordingMetaJson } from '../../__mocks__/recording_meta'
import { snapshotsAsJSONLines } from '../../__mocks__/recording_snapshots'

jest.mock('../snapshot-processing/DecompressionWorkerManager')

const playerProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('playerMetaLogic', () => {
    let logic: ReturnType<typeof playerMetaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                '/api/environments/:team_id/session_recordings/:id/snapshots/': () =>
                    new HttpResponse(snapshotsAsJSONLines()),
            },
            post: {
                '/api/environments/:team_id/query/:kind': recordingEventsJson,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        logic = playerMetaLogic(playerProps)
        logic.mount()
    })

    describe('getPropertyDisplayInfo', () => {
        it.each([
            ['core session property the recording lacks', '$entry_pathname', {}, PropertyFilterType.Session],
            ['unknown key the recording lacks', 'plan', {}, PropertyFilterType.Person],
            ['unknown key the recording has', 'custom', { custom: 1 }, PropertyFilterType.Event],
        ])('types a %s', (_, property, recordingProperties, expected) => {
            expect(getPropertyDisplayInfo(property, recordingProperties).propertyFilterType).toBe(expected)
        })
    })

    describe('core assumptions', () => {
        it('mounts other logics', () => {
            expectLogic(logic).toMount([
                sessionRecordingDataCoordinatorLogic(playerProps),
                sessionRecordingPlayerLogic(playerProps),
            ])
        })
        it('starts with loading state', () => {
            expectLogic(logic).toMatchValues({
                loading: true,
            })
        })
    })

    describe('allOverviewItems', () => {
        const metaId = recordingMetaJson.id
        const countryItem = (): any =>
            logic.values.allOverviewItems.find(
                (item) => item.type === 'property' && item.property === '$geoip_country_code'
            )

        it.each([
            ['session properties over person properties', { $geoip_country_code: 'DE' }, 'DE'],
            ['person properties when the session has none loaded', {}, 'US'],
        ])('shows %s', async (_, sessionProperties, expected) => {
            useMocks({
                get: {
                    '/api/environments/:team_id/session_recordings/:id': {
                        ...recordingMetaJson,
                        person: { ...recordingMetaJson.person, properties: { $geoip_country_code: 'US' } },
                    },
                },
            })
            await expectLogic(logic, () => {
                sessionRecordingDataCoordinatorLogic(playerProps).actions.loadRecordingMeta()
            }).toDispatchActions(['loadRecordingMetaSuccess'])
            logic.actions.loadPropertiesForSessionsSuccess([{ id: metaId, properties: sessionProperties }])

            expect(countryItem()?.value).toBe(expected)
        })
    })

    describe('startedFromEmail', () => {
        it.each([
            ['an email entry medium', { $entry_utm_medium: 'email' }, true],
            ['an email entry medium in any case', { $entry_utm_medium: 'Email' }, true],
            ['another entry medium', { $entry_utm_medium: 'cpc' }, false],
            ['a medium that only contains email', { $entry_utm_medium: 'newsletter-email' }, false],
            ['no entry medium', { $entry_utm_medium: null }, false],
        ])('reads %s', async (_, sessionProperties: Record<string, unknown>, expected) => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const { query } = (await request.json()) as { query: { query?: string } }
                        if (!query.query?.includes('$session_id as session_id')) {
                            return [200, recordingEventsJson]
                        }
                        const columns = [...query.query.matchAll(/ as (\$?\w+)/g)].map(([, column]) => column)
                        const row = columns.map((column) =>
                            column === 'session_id' ? recordingMetaJson.id : (sessionProperties[column] ?? null)
                        )
                        return [200, { results: [row] }]
                    },
                },
            })

            await expectLogic(logic, () => {
                sessionRecordingDataCoordinatorLogic(playerProps).actions.loadRecordingMeta()
            }).toDispatchActions(['loadRecordingMetaSuccess', 'loadPropertiesForSessionsSuccess'])

            expect(logic.values.startedFromEmail).toBe(expected)
        })
    })

    describe('loading state', () => {
        it('stops loading after meta load is successful', async () => {
            const session: SessionRecordingType = {
                id: '1',
            } as SessionRecordingType
            await expectLogic(logic, () => {
                sessionRecordingDataCoordinatorLogic(playerProps).actions.loadRecordingMeta()
                logic.actions.maybeLoadPropertiesForSessions([session])
            })
                .toDispatchActions(['loadRecordingMetaSuccess', 'loadPropertiesForSessionsSuccess'])
                .toMatchValues({ loading: false })
        })
    })
})
