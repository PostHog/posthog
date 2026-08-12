import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayScannerApi } from 'products/replay_vision/frontend/generated/api.schemas'

import { experimentLinkedScannersLogic } from './experimentLinkedScannersLogic'

const scanner = (id: string, name: string, variantKeys: string[]): ReplayScannerApi =>
    ({
        id,
        name,
        experiment_targeting: { experiment_id: 7, variant_keys: variantKeys, use_exposure_fallback: false },
    }) as unknown as ReplayScannerApi

describe('experimentLinkedScannersLogic', () => {
    let logic: ReturnType<typeof experimentLinkedScannersLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/vision/scanners/`]: ({ request }) => {
                    // The filter must reach the endpoint, otherwise the backend would return every
                    // scanner and the banner would over-report.
                    expect(new URL(request.url).searchParams.get('experiment_id')).toEqual('7')
                    return [
                        200,
                        {
                            count: 2,
                            results: [scanner('a', 'Checkout scanner', ['test']), scanner('b', 'Funnel scanner', [])],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = experimentLinkedScannersLogic({ experimentId: 7 })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('loads the scanners targeting the experiment on mount', async () => {
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                hasLinkedScanners: true,
                linkedScanners: [expect.objectContaining({ id: 'a' }), expect.objectContaining({ id: 'b' })],
            })
    })

    it('scannersTargetingVariant returns only scanners whose variant_keys include the key', async () => {
        await expectLogic(logic).toFinishAllListeners()
        // Scanner 'a' targets "test"; scanner 'b' targets every variant, so it lists no keys and is
        // not returned for a specific key.
        expect(logic.values.scannersTargetingVariant('test').map((s) => s.id)).toEqual(['a'])
        expect(logic.values.scannersTargetingVariant('control')).toEqual([])
    })
})
