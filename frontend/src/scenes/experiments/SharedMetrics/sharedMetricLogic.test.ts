import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { sharedMetricLogic } from './sharedMetricLogic'

const COPY_UUID = 'e4f1c0d2-7b3a-4a9e-9c0f-2d5b8a1e6c73'

describe('sharedMetricLogic', () => {
    const realCrypto = globalThis.crypto

    beforeEach(() => {
        // jsdom implements no crypto.randomUUID, which the duplicate path calls. The stub also
        // pins the copy's uuid. getRandomValues stays, because MSW draws on it.
        Object.defineProperty(globalThis, 'crypto', {
            configurable: true,
            value: {
                getRandomValues: realCrypto?.getRandomValues?.bind(realCrypto),
                randomUUID: () => COPY_UUID,
            },
        })
    })

    afterEach(() => {
        Object.defineProperty(globalThis, 'crypto', { configurable: true, value: realCrypto })
    })

    it('duplicates a shared metric without its unit-less conversion window', async () => {
        // The API rejects a new metric that carries a window without a unit, so a duplicate that
        // keeps one fails to save.
        useMocks({
            get: {
                '/api/projects/:team_id/experiment_saved_metrics/1': {
                    id: 1,
                    name: 'Pageview conversion',
                    query: {
                        uuid: 'stored-uuid',
                        kind: NodeKind.ExperimentMetric,
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: '$pageview' },
                        conversion_window: 7,
                    },
                },
            },
        })
        initKeaTests()
        const logic = sharedMetricLogic({ sharedMetricId: 1, action: 'duplicate' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadSharedMetric()).toFinishAllListeners()

        expect(logic.values.sharedMetric.query).toEqual({
            uuid: COPY_UUID,
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.EventsNode, event: '$pageview' },
        })
    })
})
