import { BuildStatusEnumApi } from 'products/canvas/frontend/generated/api.schemas'
import { TaskRunStatusEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { getGenUIGenerationProgressView } from './genUIGenerationProgress'

describe('getGenUIGenerationProgressView', () => {
    const nowMs = Date.parse('2026-08-13T10:45:30Z')

    it.each([
        [TaskRunStatusEnumApi.Queued, null, 'Waiting for generation worker'],
        [TaskRunStatusEnumApi.InProgress, null, 'Agent is building the visualization'],
        [TaskRunStatusEnumApi.Completed, BuildStatusEnumApi.Building, 'Building visualization'],
        [TaskRunStatusEnumApi.Completed, BuildStatusEnumApi.Ready, 'Publishing visualization'],
    ])('describes run %s with build %s', (runStatus, buildStatus, expectedLabel) => {
        const view = getGenUIGenerationProgressView(
            {
                buildStatus,
                runCreatedAt: '2026-08-13T10:43:00Z',
                runStage: null,
                runStatus,
                runUpdatedAt: '2026-08-13T10:45:15Z',
            },
            nowMs,
            nowMs
        )

        expect(view).toEqual({
            label: expectedLabel,
            detail: 'Elapsed 2m 30s · Updated just now',
        })
    })

    it('shows the agent stage and a stale task update', () => {
        const view = getGenUIGenerationProgressView(
            {
                buildStatus: null,
                runCreatedAt: '2026-08-13T10:35:00Z',
                runStage: 'writing_visualization',
                runStatus: TaskRunStatusEnumApi.InProgress,
                runUpdatedAt: '2026-08-13T10:40:00Z',
            },
            nowMs,
            nowMs
        )

        expect(view).toEqual({
            label: 'Writing visualization',
            detail: 'Elapsed 10m 30s · Last task update 5m 30s ago',
        })
    })
})
