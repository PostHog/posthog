import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { HeatmapType } from '~/types'

import { savedCreate, savedPartialUpdate, savedRetrieve } from 'products/web_analytics/frontend/generated/api'

import { heatmapLogic, resolveHeatmapExportUrl } from './heatmapLogic'

jest.mock('products/web_analytics/frontend/generated/api')

describe('heatmapLogic', () => {
    describe('resolveHeatmapExportUrl', () => {
        const origin = 'https://us.posthog.com'

        it.each([
            [
                'screenshot',
                '/api/environments/1/heatmap_screenshots/42/content/?width=1400',
                'https://example.com/page',
                `${origin}/api/environments/1/heatmap_screenshots/42/content/?width=1400`,
            ],
            [
                'iframe',
                '/api/environments/1/heatmap_screenshots/42/content/',
                'https://example.com/page',
                'https://example.com/page',
            ],
            ['screenshot', null, 'https://example.com/page', ''],
            ['iframe', '/api/something', null, ''],
            [
                'screenshot',
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
                null,
                'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
            ],
        ] as const)(
            'resolveHeatmapExportUrl(%s, screenshotUrl=%s, displayUrl=%s) → %s',
            (type, screenshotUrl, displayUrl, expected) => {
                expect(resolveHeatmapExportUrl(type as HeatmapType, screenshotUrl, displayUrl, origin)).toBe(expected)
            }
        )
    })

    describe('createHeatmap', () => {
        let logic: ReturnType<typeof heatmapLogic.build>

        beforeEach(() => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            jest.mocked(savedCreate).mockResolvedValue({ short_id: 'new-id' } as any)
            logic = heatmapLogic({ id: 'new' })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            jest.restoreAllMocks()
        })

        it('does not hit the API when the page URL is empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.createHeatmap()
            }).toFinishAllListeners()
            expect(savedCreate).not.toHaveBeenCalled()
        })

        it('posts the trimmed URL rather than an empty string', async () => {
            logic.actions.setDisplayUrl('  https://example.com/pricing  ')
            await expectLogic(logic, () => {
                logic.actions.createHeatmap()
            }).toFinishAllListeners()
            expect(savedCreate).toHaveBeenCalledWith(
                expect.any(String),
                expect.objectContaining({ url: 'https://example.com/pricing' })
            )
        })
    })

    describe('updateHeatmap', () => {
        let logic: ReturnType<typeof heatmapLogic.build>

        beforeEach(async () => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            jest.mocked(savedRetrieve).mockResolvedValue({
                id: 1,
                short_id: 'abc',
                name: 'Test heatmap',
                url: 'https://old.example.com',
                data_url: 'https://old.example.com',
                type: 'iframe',
                block_consent_modals: false,
                status: 'completed',
                has_content: false,
            } as any)
            logic = heatmapLogic({ id: 'abc' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => {
            logic?.unmount()
            jest.restoreAllMocks()
        })

        it('keeps the edited URL in the field when the save fails', async () => {
            logic.actions.setDisplayUrl('https://new.example.com')
            jest.mocked(savedPartialUpdate).mockRejectedValueOnce(new Error('rejected'))

            await expectLogic(logic, () => {
                logic.actions.updateHeatmap()
            }).toFinishAllListeners()

            expect(logic.values.displayUrl).toBe('https://new.example.com')
            expect(logic.values.pageUrlDraft).toBe('https://new.example.com')
        })
    })
})
