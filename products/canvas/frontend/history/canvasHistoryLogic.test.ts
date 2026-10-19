import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CanvasBuildsResponseApi } from '../generated/api.schemas'
import { canvasHistoryLogic } from './canvasHistoryLogic'

describe('canvasHistoryLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': {
                    canvas: { id: 'canvas', channel: 'space', kind: 'freeform', generation_task_id: null },
                    current_version_id: 'head',
                    published_build: null,
                    has_active_build: false,
                },
                '/api/projects/:team_id/task_channels/:id/': { id: 'space', name: 'Space' },
                '/api/projects/:team_id/canvases/:id/versions/': { results: [], next: null },
                '/api/projects/:team_id/canvases/:id/drafts/': [],
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
            },
        })
        initKeaTests()
    })

    it('refreshes loaded history only when a polled build changes', async () => {
        const logic = canvasHistoryLogic({ id: 'canvas' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadViewSuccess'])
        const history = {
            current_version_id: 'head',
            published_build_id: null,
            builds: [{ id: 'build', source_version_id: 'head', build_status: 'queued' }],
        } as CanvasBuildsResponseApi
        logic.actions.loadBuildHistorySuccess(history)

        await expectLogic(logic, () => logic.actions.loadBuildsSuccess(history)).toNotHaveDispatchedActions([
            'loadBuildHistory',
        ])
        await expectLogic(logic, () =>
            logic.actions.loadBuildsSuccess({ ...history, builds: [{ ...history.builds[0], build_status: 'failed' }] })
        ).toDispatchActions(['loadBuildHistory', 'loadBuildHistorySuccess'])
    })

    test.each([true, false])('loads a preview when a retained build exists: %s', async (built) => {
        const project = {
            schemaVersion: 1,
            entryHtml: 'index.html',
            files: {
                'src/canvas.tsx': 'import { title } from "./title"; export default () => <h1>{title}</h1>',
                'src/title.ts': 'export const title = "Preview"',
            },
        }
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/builds/': {
                    builds: built
                        ? [
                              {
                                  id: 'build',
                                  source_version_id: 'previous',
                                  build_status: 'ready',
                                  artifact_url: 'https://example.com/build',
                              },
                          ]
                        : [],
                    published_build_id: null,
                },
                '/api/projects/:team_id/canvases/:id/source/': built
                    ? [503, { detail: 'Source unavailable' }]
                    : { project },
            },
        })
        const logic = canvasHistoryLogic({ id: 'canvas' })
        logic.mount()
        logic.actions.loadBrowsedRender({ versionId: 'previous' })
        await expectLogic(logic).toDispatchActions(['loadBrowsedRenderSuccess'])
        expect(logic.values.browsedRender?.versionId).toBe('previous')
        if (built) {
            expect(logic.values.browsedRender?.build?.id).toBe('build')
        } else {
            expect(logic.values.browsedRender?.project).toEqual(project)
        }
    })
})
