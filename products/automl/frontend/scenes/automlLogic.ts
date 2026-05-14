import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import {
    type ParquetPreview,
    type QueryText,
    type RunDetail,
    type TaskDetail,
    type TaskSummary,
    getQuery,
    getRun,
    getTask,
    listTasks,
    previewParquet,
} from '../api'
import type { automlLogicType } from './automlLogicType'

export const automlLogic = kea<automlLogicType>([
    path(['products', 'automl', 'automlLogic']),

    actions({
        setSelectedTask: (name: string | null) => ({ name }),
        setSelectedRun: (runId: string | null) => ({ runId }),
        setSelectedQuery: (version: string | null) => ({ version }),
        setPreviewArtifact: (artifact: string) => ({ artifact }),
        setPreviewPageSize: (pageSize: number) => ({ pageSize }),
        setPreviewPage: (page: number) => ({ page }),
    }),

    reducers({
        selectedTask: [
            null as string | null,
            {
                setSelectedTask: (_, { name }) => name,
            },
        ],
        selectedRun: [
            null as string | null,
            {
                setSelectedRun: (_, { runId }) => runId,
            },
        ],
        selectedQuery: [
            null as string | null,
            {
                setSelectedQuery: (_, { version }) => version,
            },
        ],
        previewArtifact: [
            'predictions.parquet',
            {
                setPreviewArtifact: (_, { artifact }) => artifact,
            },
        ],
        previewPageSize: [
            25,
            {
                setPreviewPageSize: (_, { pageSize }) => pageSize,
            },
        ],
        previewPage: [
            1,
            {
                setPreviewPage: (_, { page }) => Math.max(1, page),
                setPreviewArtifact: () => 1,
                setPreviewPageSize: () => 1,
                setSelectedRun: () => 1,
            },
        ],
    }),

    loaders(({ values }) => ({
        tasks: [
            [] as TaskSummary[],
            {
                loadTasks: async () => {
                    return await listTasks()
                },
            },
        ],
        taskDetail: [
            null as TaskDetail | null,
            {
                loadTask: async ({ name }: { name: string }) => {
                    return await getTask(name)
                },
                clearTask: () => null,
            },
        ],
        runDetail: [
            null as RunDetail | null,
            {
                loadRun: async ({ name, runId }: { name: string; runId: string }) => {
                    return await getRun(name, runId)
                },
                clearRun: () => null,
            },
        ],
        queryText: [
            null as QueryText | null,
            {
                loadQuery: async ({ name, version }: { name: string; version: string }) => {
                    return await getQuery(name, version)
                },
                clearQuery: () => null,
            },
        ],
        preview: [
            null as ParquetPreview | null,
            {
                loadPreview: async ({ name, runId }: { name: string; runId: string }) => {
                    const offset = (values.previewPage - 1) * values.previewPageSize
                    return await previewParquet(name, runId, values.previewArtifact, values.previewPageSize, offset)
                },
                clearPreview: () => null,
            },
        ],
    })),

    selectors({
        currentTask: [
            (s) => [s.tasks, s.selectedTask],
            (tasks, selectedTask): TaskSummary | null =>
                selectedTask ? (tasks.find((t) => t.name === selectedTask) ?? null) : null,
        ],
    }),

    listeners(({ actions, values }) => ({
        setSelectedTask: ({ name }) => {
            if (name) {
                actions.loadTask({ name })
            } else {
                actions.clearTask()
            }
        },
        setSelectedRun: ({ runId }) => {
            if (runId && values.selectedTask) {
                actions.loadRun({ name: values.selectedTask, runId })
                actions.loadPreview({ name: values.selectedTask, runId })
            } else {
                actions.clearRun()
                actions.clearPreview()
            }
        },
        setSelectedQuery: ({ version }) => {
            if (version && values.selectedTask) {
                actions.loadQuery({ name: values.selectedTask, version })
            } else {
                actions.clearQuery()
            }
        },
        setPreviewArtifact: () => {
            if (values.selectedTask && values.selectedRun) {
                actions.loadPreview({ name: values.selectedTask, runId: values.selectedRun })
            }
        },
        setPreviewPageSize: () => {
            if (values.selectedTask && values.selectedRun) {
                actions.loadPreview({ name: values.selectedTask, runId: values.selectedRun })
            }
        },
        setPreviewPage: () => {
            if (values.selectedTask && values.selectedRun) {
                actions.loadPreview({ name: values.selectedTask, runId: values.selectedRun })
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.automlTasks()]: () => {
            if (values.selectedTask !== null) {
                actions.setSelectedTask(null)
            }
            if (values.selectedRun !== null) {
                actions.setSelectedRun(null)
            }
        },
        [urls.automlTask(':name')]: ({ name }) => {
            if (values.selectedTask !== name) {
                actions.setSelectedTask(name || null)
            }
            if (values.selectedRun !== null) {
                actions.setSelectedRun(null)
            }
        },
        [urls.automlRun(':name', ':runId')]: ({ name, runId }) => {
            if (values.selectedTask !== name) {
                actions.setSelectedTask(name || null)
            }
            if (values.selectedRun !== runId) {
                actions.setSelectedRun(runId || null)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTasks()
    }),
])
