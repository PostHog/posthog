import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { canvasesViewRetrieve } from 'products/canvas/frontend/generated/api'
import type { CanvasViewResponseApi } from 'products/canvas/frontend/generated/api.schemas'

import { canvasAppWidgetLogic } from './canvasAppWidgetLogic'

jest.mock('products/canvas/frontend/generated/api', () => ({
    canvasesViewRetrieve: jest.fn(),
}))

const CANVAS_ID = '11111111-1111-1111-1111-111111111111'

function view(overrides: Partial<CanvasViewResponseApi> = {}): CanvasViewResponseApi {
    return {
        canvas: { id: CANVAS_ID, name: 'Launch board', channel: 'space-1', url: '/canvases/x' },
        published_build: {
            id: 'build-1',
            source_version_id: 'version-1',
            build_status: 'ready',
            diagnostics: [],
            integrity: 'abc',
            artifact_url: 'https://artifacts.example.com/canvas-artifacts/token/index.html',
            manifest: {
                entryHtml: 'index.html',
                assets: [],
                dependencies: {},
                canvasSdkVersion: '0.2.0',
                capabilities: { posthog: { insights: [], inlineQueries: true, captureEvents: [] }, network: {} },
            },
        },
        current_version_id: 'version-1',
        has_active_build: false,
        ...overrides,
    } as unknown as CanvasViewResponseApi
}

describe('canvasAppWidgetLogic', () => {
    let logic: ReturnType<typeof canvasAppWidgetLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = canvasAppWidgetLogic({ tileId: 1, canvasId: CANVAS_ID })
    })

    afterEach(() => logic.unmount())

    it('exposes the live build and the capabilities frozen into it', async () => {
        jest.mocked(canvasesViewRetrieve).mockResolvedValue(view())

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(canvasesViewRetrieve).toHaveBeenCalledWith(expect.any(String), CANVAS_ID)
        expect(logic.values.renderState).toEqual('built')
        expect(logic.values.artifactUrl).toEqual('https://artifacts.example.com/canvas-artifacts/token/index.html')
        expect(logic.values.capabilities).toEqual({
            posthog: { insights: [], inlineQueries: true, captureEvents: [] },
            network: {},
        })
        expect(logic.values.hostProps).toEqual({
            canvasId: CANVAS_ID,
            spaceId: 'space-1',
            sourceVersionId: 'version-1',
            instanceKey: 'dashboard-tile-1',
        })
    })

    it('gives each tile of the same canvas its own host instance', async () => {
        jest.mocked(canvasesViewRetrieve).mockResolvedValue(view())
        const other = canvasAppWidgetLogic({ tileId: 2, canvasId: CANVAS_ID })

        await expectLogic(logic, () => {
            logic.mount()
            other.mount()
        }).toFinishAllListeners()

        expect(logic.values.hostProps.instanceKey).toEqual('dashboard-tile-1')
        expect(other.values.hostProps.instanceKey).toEqual('dashboard-tile-2')
        other.unmount()
    })

    it('loads the view again when the dashboard result reports a new live build', async () => {
        jest.mocked(canvasesViewRetrieve).mockResolvedValue(view())
        logic = canvasAppWidgetLogic({ tileId: 1, canvasId: CANVAS_ID, publishedBuildId: 'build-1' })

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(canvasesViewRetrieve).toHaveBeenCalledTimes(1)

        jest.mocked(canvasesViewRetrieve).mockResolvedValue(
            view({ published_build: { ...view().published_build!, id: 'build-2' } })
        )
        await expectLogic(logic, () => {
            canvasAppWidgetLogic({ tileId: 1, canvasId: CANVAS_ID, publishedBuildId: 'build-2' })
        }).toFinishAllListeners()

        expect(canvasesViewRetrieve).toHaveBeenCalledTimes(2)
        expect(logic.values.buildId).toEqual('build-2')
    })

    it.each([403, 404])('reports a %s response as an unavailable canvas, not a connection failure', async (status) => {
        jest.mocked(canvasesViewRetrieve).mockRejectedValue(Object.assign(new Error('nope'), { status }))

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.renderState).toEqual('unavailable')
    })

    it('reports a canvas that has nothing built yet instead of rendering a blank frame', async () => {
        jest.mocked(canvasesViewRetrieve).mockResolvedValue(view({ published_build: null }))

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.renderState).toEqual('not-published')
        expect(logic.values.artifactUrl).toBeNull()
    })

    it('reports a load failure so the tile can offer a retry', async () => {
        jest.mocked(canvasesViewRetrieve).mockRejectedValue(new Error('boom'))

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.renderState).toEqual('error')
    })
})
