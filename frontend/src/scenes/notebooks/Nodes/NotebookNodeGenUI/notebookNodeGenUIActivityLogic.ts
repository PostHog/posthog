import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { runStreamLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ThreadItem, ToolInvocation } from 'products/posthog_ai/frontend/api/types'
import { tasksRetrieve } from 'products/tasks/frontend/generated/api'

import { type GenUIGenerationActivityItem, selectGenUIGenerationActivity } from './genUIGenerationActivity'

export interface NotebookNodeGenUIActivityLogicProps {
    taskId: string
}

export interface notebookNodeGenUIActivityLogicValues {
    activityItems: GenUIGenerationActivityItem[]
    currentProgress: string | null
    currentTeamId: number | null
    taskRunError: string | null
    taskRunLoading: boolean
    threadItems: ThreadItem[]
    toolInvocations: Map<string, ToolInvocation>
}

export interface notebookNodeGenUIActivityLogicActions {
    bootstrapRun: (payload: { justCreatedRun?: boolean; runId: string; taskId: string; traceId?: string }) => {
        justCreatedRun?: boolean
        runId: string
        taskId: string
        traceId?: string
    }
    loadTaskRun: () => { value: true }
    taskRunFailed: (error: string) => { error: string }
    taskRunReceived: (runId: string) => { runId: string }
}

export interface notebookNodeGenUIActivityLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        activityItems: (
            threadItems: ThreadItem[],
            toolInvocations: Map<string, ToolInvocation>,
            currentProgress: string | null
        ) => GenUIGenerationActivityItem[]
    }
}

export type notebookNodeGenUIActivityLogicType = MakeLogicType<
    notebookNodeGenUIActivityLogicValues,
    notebookNodeGenUIActivityLogicActions,
    NotebookNodeGenUIActivityLogicProps,
    notebookNodeGenUIActivityLogicMeta
>

export const notebookNodeGenUIActivityLogic: LogicWrapper<notebookNodeGenUIActivityLogicType> =
    kea<notebookNodeGenUIActivityLogicType>([
        props({} as NotebookNodeGenUIActivityLogicProps),
        key((props) => props.taskId),
        path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeGenUIActivityLogic', key]),
        connect((props: NotebookNodeGenUIActivityLogicProps) => ({
            values: [
                teamLogic,
                ['currentTeamId'],
                runStreamLogic({ streamKey: props.taskId }),
                ['currentProgress', 'threadItems', 'toolInvocations'],
            ],
            actions: [runStreamLogic({ streamKey: props.taskId }), ['bootstrapRun']],
        })),
        actions({
            loadTaskRun: true,
            taskRunFailed: (error: string) => ({ error }),
            taskRunReceived: (runId: string) => ({ runId }),
        }),
        reducers({
            taskRunLoading: [
                false,
                {
                    loadTaskRun: () => true,
                    taskRunFailed: () => false,
                    taskRunReceived: () => false,
                },
            ],
            taskRunError: [
                null as string | null,
                {
                    loadTaskRun: () => null,
                    taskRunFailed: (_, { error }) => error,
                    taskRunReceived: () => null,
                },
            ],
        }),
        selectors({
            activityItems: [
                (selectors) => [selectors.threadItems, selectors.toolInvocations, selectors.currentProgress],
                selectGenUIGenerationActivity,
            ],
        }),
        listeners(({ actions, values, props }) => ({
            loadTaskRun: async (_, breakpoint) => {
                if (!values.currentTeamId) {
                    actions.taskRunFailed('Live agent activity is unavailable. Open the task to follow its progress.')
                    return
                }
                const task = await tasksRetrieve(String(values.currentTeamId), props.taskId).catch(() => null)
                breakpoint()
                if (!task) {
                    actions.taskRunFailed('Live agent activity is unavailable. Open the task to follow its progress.')
                    return
                }
                if (!task.latest_run?.id) {
                    actions.taskRunFailed('Live agent activity is not ready yet. Open the task to follow its progress.')
                    return
                }
                actions.taskRunReceived(task.latest_run.id)
            },
            taskRunReceived: ({ runId }) => {
                actions.bootstrapRun({ taskId: props.taskId, runId })
            },
        })),
        afterMount(({ actions }) => {
            actions.loadTaskRun()
        }),
    ])
