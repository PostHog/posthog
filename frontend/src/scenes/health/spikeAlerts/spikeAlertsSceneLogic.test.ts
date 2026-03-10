import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SpikeAlertsResponse, spikeAlertsSceneLogic } from './spikeAlertsSceneLogic'

const MOCK_ALERT_EVENTS = {
    id: 'alert-events',
    spike_date: '2026-02-28',
    detected_at: '2026-02-28T20:22:43.663000',
    detected_spikes: [
        {
            usage_key: 'events',
            value: '479,340',
            weekday_average: '330,619',
            z_score: 4.66,
        },
    ],
}

const MOCK_ALERT_RECORDINGS = {
    id: 'alert-recordings',
    spike_date: '2026-02-27',
    detected_at: '2026-02-27T18:00:00.000000',
    detected_spikes: [
        {
            usage_key: 'recordings',
            value: '1,000',
            weekday_average: '800',
            z_score: 2.5,
        },
    ],
}

const MOCK_RESPONSE: SpikeAlertsResponse = {
    results: [MOCK_ALERT_EVENTS, MOCK_ALERT_RECORDINGS],
    count: 2,
}

describe('spikeAlertsSceneLogic', () => {
    let logic: ReturnType<typeof spikeAlertsSceneLogic.build>

    function mountWithFlag(flagEnabled: boolean): void {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.SPIKE_ALERTS_PAGE]: flagEnabled,
        })
        logic = spikeAlertsSceneLogic()
        logic.mount()
    }

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
    })

    it('loads and flattens spike alerts on mount when flag is enabled', async () => {
        useMocks({
            get: {
                '/api/environments/@current/spike_alerts/': () => [200, MOCK_RESPONSE],
            },
        })

        mountWithFlag(true)

        await expectLogic(logic)
            .toDispatchActions(['loadSpikeAlerts', 'loadSpikeAlertsSuccess'])
            .toMatchValues({
                flatAlerts: [
                    expect.objectContaining({ usage_key: 'events', spike_date: '2026-02-28' }),
                    expect.objectContaining({ usage_key: 'recordings', spike_date: '2026-02-27' }),
                ],
            })
    })

    it('redirects to /health when feature flag is disabled', async () => {
        useMocks({
            get: {
                '/api/environments/@current/spike_alerts/': () => [200, MOCK_RESPONSE],
            },
        })

        mountWithFlag(false)

        await expectLogic(logic).toDispatchActions([router.actionCreators.replace(urls.health())])
    })

    it('filters flat rows by metric name', async () => {
        useMocks({
            get: {
                '/api/environments/@current/spike_alerts/': () => [200, MOCK_RESPONSE],
            },
        })

        mountWithFlag(true)

        await expectLogic(logic).toDispatchActions(['loadSpikeAlertsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('events')
        }).toMatchValues({
            filteredAlerts: [expect.objectContaining({ usage_key: 'events' })],
        })
    })

    it('returns all flat rows when search term is empty', async () => {
        useMocks({
            get: {
                '/api/environments/@current/spike_alerts/': () => [200, MOCK_RESPONSE],
            },
        })

        mountWithFlag(true)

        await expectLogic(logic).toDispatchActions(['loadSpikeAlertsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('')
        }).toMatchValues({
            filteredAlerts: expect.arrayContaining([
                expect.objectContaining({ usage_key: 'events' }),
                expect.objectContaining({ usage_key: 'recordings' }),
            ]),
        })

        await expectLogic(logic, () => {
            logic.actions.setSearchTerm('   ')
        }).toMatchValues({
            filteredAlerts: expect.arrayContaining([
                expect.objectContaining({ usage_key: 'events' }),
                expect.objectContaining({ usage_key: 'recordings' }),
            ]),
        })
    })

    it('exposes correct breadcrumbs', async () => {
        useMocks({
            get: {
                '/api/environments/@current/spike_alerts/': () => [200, MOCK_RESPONSE],
            },
        })

        mountWithFlag(true)

        await expectLogic(logic).toMatchValues({
            breadcrumbs: [
                expect.objectContaining({
                    key: Scene.Health,
                    path: urls.health(),
                }),
                expect.objectContaining({
                    key: Scene.SpikeAlerts,
                    name: 'Spike alerts',
                }),
            ],
        })
    })
})
