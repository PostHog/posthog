import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import { NotebookNodeDataV2Result } from './NotebookNodeDataV2'
import type { notebookNodeDataV2LogicType } from './notebookNodeDataV2LogicType'

export interface NotebookNodeDataV2LogicProps {
    nodeId: string
    notebookShortId: string
    updateAttributes: (attrs: { runId?: string | null; result?: NotebookNodeDataV2Result | null }) => void
}

export const notebookNodeDataV2Logic = kea<notebookNodeDataV2LogicType>([
    path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeDataV2Logic', key]),
    props({} as NotebookNodeDataV2LogicProps),
    key((props) => props.nodeId),
    actions({
        runQuery: (code: string) => ({ code }),
        startInstance: true,
        setIsRunning: (isRunning: boolean) => ({ isRunning }),
        setIsStarting: (isStarting: boolean) => ({ isStarting }),
        setRunError: (runError: string | null) => ({ runError }),
    }),
    reducers({
        isRunning: [
            false,
            {
                runQuery: () => true,
                setIsRunning: (_, { isRunning }) => isRunning,
            },
        ],
        isStarting: [
            false,
            {
                startInstance: () => true,
                setIsStarting: (_, { isStarting }) => isStarting,
            },
        ],
        runError: [
            null as string | null,
            {
                runQuery: () => null,
                startInstance: () => null,
                setRunError: (_, { runError }) => runError,
            },
        ],
    }),
    listeners(({ props, actions }) => ({
        startInstance: async () => {
            try {
                await api.notebooks.dataV2Start(props.notebookShortId)
            } catch (error) {
                actions.setRunError(error instanceof Error ? error.message : 'Failed to start instance')
            } finally {
                actions.setIsStarting(false)
            }
        },
        runQuery: async ({ code }) => {
            try {
                const { run_id } = await api.notebooks.dataV2Run(props.notebookShortId, {
                    node_id: props.nodeId,
                    code,
                })
                props.updateAttributes({ runId: run_id })
                await api.notebooks.dataV2RunStream(props.notebookShortId, run_id, {
                    onMessage: (message) => {
                        const parsed = JSON.parse(message.data)
                        if (message.event === 'result') {
                            props.updateAttributes({
                                result: {
                                    columns: parsed.columns ?? [],
                                    row_count: parsed.row_count ?? 0,
                                    first_page: parsed.first_page ?? [],
                                },
                            })
                        } else if (message.event === 'error') {
                            actions.setRunError(parsed.error ?? 'Run failed')
                        }
                    },
                    onError: (error) => {
                        actions.setRunError(error instanceof Error ? error.message : String(error))
                    },
                })
            } catch (error) {
                actions.setRunError(error instanceof Error ? error.message : 'Failed to run query')
            } finally {
                actions.setIsRunning(false)
            }
        },
    })),
])
