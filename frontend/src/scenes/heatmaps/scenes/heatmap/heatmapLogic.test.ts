import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { HeatmapType } from '~/types'

import { savedPartialUpdate, savedRegenerateCreate, savedRetrieve } from 'products/web_analytics/frontend/generated/api'
import type { HeatmapScreenshotResponseApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { heatmapLogic, resolveHeatmapExportUrl } from './heatmapLogic'

jest.mock('products/web_analytics/frontend/generated/api', () => {
    const actual = jest.requireActual('products/web_analytics/frontend/generated/api')
    return {
        ...actual,
        savedRetrieve: jest.fn(),
        savedPartialUpdate: jest.fn(),
        savedRegenerateCreate: jest.fn(),
    }
})

function makeHeatmap(overrides: Partial<HeatmapScreenshotResponseApi> = {}): HeatmapScreenshotResponseApi {
    return {
        id: 'hm_1',
        short_id: 'abc123',
        name: 'Test heatmap',
        url: 'https://example.com',
        data_url: 'https://example.com',
        target_widths: [1024],
        type: 'iframe',
        status: 'completed',
        has_content: false,
        snapshots: [],
        deleted: false,
        block_consent_modals: false,
        created_by: null,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        exception: null,
        user_access_level: null,
        ...overrides,
    } as HeatmapScreenshotResponseApi
}

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

    describe('screenshot regeneration', () => {
        beforeEach(() => {
            initKeaTests()
            jest.mocked(savedRetrieve).mockResolvedValue(makeHeatmap())
            // Reject rather than resolve: a successful regenerate kicks off the real
            // `pollScreenshotStatus` listener, which loops on a 2s timer for up to 5 minutes.
            // These tests only care whether/when `savedRegenerateCreate` was called, not what
            // happens after a successful render, so keep the listener tree short-lived.
            jest.mocked(savedRegenerateCreate).mockRejectedValue({ status: 500 })
        })

        it('does not fire a regenerate before the capture-method PATCH has actually persisted', async () => {
            const logic = heatmapLogic({ id: 'abc123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            let resolvePatch: ((value: HeatmapScreenshotResponseApi) => void) | undefined
            jest.mocked(savedPartialUpdate).mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolvePatch = resolve
                    })
            )

            logic.actions.changeCaptureMethod('screenshot')
            await expectLogic(logic).toDispatchActions(['setLoading'])

            // The PATCH that persists `type: 'screenshot'` is still in flight — regenerating now
            // would hit the backend while it still sees the old type, so it must not fire yet.
            expect(savedRegenerateCreate).not.toHaveBeenCalled()

            resolvePatch?.(makeHeatmap({ type: 'screenshot' }))
            await expectLogic(logic).toFinishAllListeners()

            expect(savedRegenerateCreate).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['detail', { status: 400, detail: 'Only screenshot heatmaps can be regenerated' }],
            ['error', { status: 400, error: 'Only screenshot heatmaps can be regenerated' }],
        ])('surfaces the backend regenerate error from a %s-shaped response', async (_shape, apiError) => {
            const logic = heatmapLogic({ id: 'abc123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            jest.mocked(savedRegenerateCreate).mockRejectedValue(apiError)

            logic.actions.regenerateScreenshot()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.screenshotError).toBe('Only screenshot heatmaps can be regenerated')
        })

        it('retryScreenshot re-syncs the heatmap before asking for a new render', async () => {
            const logic = heatmapLogic({ id: 'abc123' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const callOrder: string[] = []
            jest.mocked(savedPartialUpdate).mockImplementation(async () => {
                callOrder.push('update')
                return makeHeatmap({ type: 'screenshot' })
            })
            jest.mocked(savedRegenerateCreate).mockImplementation(async () => {
                callOrder.push('regenerate')
                throw { status: 500 }
            })

            logic.actions.retryScreenshot()
            await expectLogic(logic).toFinishAllListeners()

            expect(callOrder).toEqual(['update', 'regenerate'])
        })
    })
})
