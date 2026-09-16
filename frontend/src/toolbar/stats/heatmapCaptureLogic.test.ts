import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { heatmapCaptureLogic } from '~/toolbar/stats/heatmapCaptureLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
jest.mock('~/toolbar/utils/screenshot', () => ({
    captureElementScreenshot: jest.fn(() => Promise.resolve(new Blob(['fake-image'], { type: 'image/jpeg' }))),
}))
jest.mock('~/toolbar/utils/responsiveScreenshot', () => ({
    RESPONSIVE_CAPTURE_WIDTHS: [320, 768, 1440],
    captureResponsiveScreenshots: jest.fn(),
}))

const { captureResponsiveScreenshots } = jest.requireMock('~/toolbar/utils/responsiveScreenshot')

const jpeg = (): Blob => new Blob(['fake-image'], { type: 'image/jpeg' })

const mockCaptureResponse = (): void => {
    global.fetch = jest.fn(() =>
        Promise.resolve({
            ok: true,
            status: 201,
            json: () => Promise.resolve({ id: 'uuid-1', short_id: 'hm123' }),
        } as any as Response)
    )
}

describe('heatmapCaptureLogic', () => {
    beforeAll(silenceKeaLoadersErrors)
    afterAll(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof heatmapCaptureLogic.build>

    beforeEach(() => {
        initKeaTests()
        window.innerWidth = 1440
        ;(captureResponsiveScreenshots as jest.Mock).mockReset()
        toolbarConfigLogic
            .build({
                apiURL: 'http://localhost',
                accessToken: 'test-token',
                refreshToken: 'test-refresh',
                clientId: 'test-client',
            })
            .mount()
        logic = heatmapCaptureLogic()
        logic.mount()
        currentPageLogic.actions.setHref('https://app.example.com/dashboard')
    })

    it.each([
        {
            name: 'uploads one image per captured width as parallel images/widths arrays',
            captures: [
                { width: 320, blob: jpeg() },
                { width: 768, blob: jpeg() },
                { width: 1440, blob: jpeg() },
            ],
            expectedWidths: ['320', '768', '1440'],
            expectedImageCount: 3,
            expectedSingleWidth: null as string | null,
        },
        {
            name: 'falls back to a single capture at the current width when no widths could be reflowed',
            captures: [] as { width: number; blob: Blob }[],
            expectedWidths: [] as string[],
            expectedImageCount: 0,
            expectedSingleWidth: '1440' as string | null,
        },
    ])('$name', async ({ captures, expectedWidths, expectedImageCount, expectedSingleWidth }) => {
        ;(captureResponsiveScreenshots as jest.Mock).mockResolvedValue(captures)
        mockCaptureResponse()

        await expectLogic(logic, () => {
            logic.actions.saveToPostHog()
        })
            .delay(0)
            .toDispatchActions(['saveToPostHog', 'saveToPostHogSuccess'])

        const [url, options] = (global.fetch as jest.Mock).mock.calls[0]
        expect(url).toContain('/api/projects/@current/saved/capture/')
        const body = options.body as FormData
        expect(body.get('url')).toBe('https://app.example.com/dashboard')
        expect(body.getAll('widths')).toEqual(expectedWidths)
        const images = body.getAll('images')
        expect(images).toHaveLength(expectedImageCount)
        expect(images.every((image) => image instanceof File)).toBe(true)
        expect(body.get('width')).toBe(expectedSingleWidth)
        expect(body.get('image') instanceof File).toBe(expectedSingleWidth !== null)
    })
})
