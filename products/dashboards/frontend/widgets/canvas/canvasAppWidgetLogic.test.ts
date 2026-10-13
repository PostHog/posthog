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
        })
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
