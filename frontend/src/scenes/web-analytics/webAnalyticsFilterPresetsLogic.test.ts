import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import type { PaginatedResponse } from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { WebAnalyticsFilterPresetType } from '~/types'

import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'

const makePreset = (shortId: string, pinned: boolean): WebAnalyticsFilterPresetType =>
    ({
        short_id: shortId,
        name: `Preset ${shortId}`,
        description: '',
        pinned,
        filters: {},
    }) as unknown as WebAnalyticsFilterPresetType

// Eight unpinned presets so the old five-item cap would drop three of them.
const unpinned = Array.from({ length: 8 }, (_, i) => makePreset(`u${i}`, false))
const pinned = [makePreset('p0', true)]

describe('webAnalyticsFilterPresetsLogic', () => {
    let logic: ReturnType<typeof webAnalyticsFilterPresetsLogic.build>

    useMocks({
        get: {
            '/api/environments/:team_id/web_analytics_filter_presets': () => [
                200,
                { results: [...pinned, ...unpinned], count: 9 },
            ],
        },
    })

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'get')
        logic = webAnalyticsFilterPresetsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('exposes every unpinned preset instead of capping the list', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.unpinnedPresets).toHaveLength(8)
        expect(logic.values.pinnedPresets).toHaveLength(1)
    })

    it('sends the search term to the backend when filtering presets', async () => {
        await expectLogic(logic).toFinishAllListeners()
        api.get.mockClear()

        logic.actions.setPresetSearchTerm('mobile')
        await expectLogic(logic).toFinishAllListeners()

        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('search=mobile'), undefined)
    })

    it('keeps the latest response when an earlier request resolves last', async () => {
        await expectLogic(logic).toFinishAllListeners()

        let resolveEarlier: (response: PaginatedResponse<WebAnalyticsFilterPresetType>) => void = () => {}
        let resolveNewer: (response: PaginatedResponse<WebAnalyticsFilterPresetType>) => void = () => {}
        const earlierRequest = new Promise<PaginatedResponse<WebAnalyticsFilterPresetType>>((resolve) => {
            resolveEarlier = resolve
        })
        const newerRequest = new Promise<PaginatedResponse<WebAnalyticsFilterPresetType>>((resolve) => {
            resolveNewer = resolve
        })

        api.get.mockImplementationOnce(() => earlierRequest).mockImplementationOnce(() => newerRequest)

        logic.actions.loadPresets()
        logic.actions.loadPresets()

        // The newer request settles first; the earlier one lands afterwards and must not overwrite it.
        resolveNewer({ results: [makePreset('newer', false)] })
        resolveEarlier({ results: [makePreset('earlier', false)] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.presets.results).toHaveLength(1)
        expect(logic.values.presets.results[0].short_id).toBe('newer')
    })
})
