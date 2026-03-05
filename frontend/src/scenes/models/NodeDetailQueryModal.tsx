import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { SQLEditor } from 'scenes/data-warehouse/editor/SQLEditor'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

export function NodeDetailQueryModal({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const logicProps = { id }
    const { savedQuery, node, queryModalOpen } = useValues(nodeDetailSceneLogic(logicProps))
    const { closeQueryModal } = useActions(nodeDetailSceneLogic(logicProps))
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { sidePanelWidth } = useValues(panelLayoutLogic)

    const sqlEditorTabId = useMemo(() => `node-detail-query-${id}`, [id])
    const sqlEditorProps = useMemo(() => ({ tabId: sqlEditorTabId, mode: SQLEditorMode.Embedded }), [sqlEditorTabId])
    const { queryInput } = useValues(sqlEditorLogic(sqlEditorProps))
    const { setQueryInput, setSourceQuery, runQuery, updateView } = useActions(sqlEditorLogic(sqlEditorProps))

    const query = savedQuery?.query?.query
    const variables = savedQuery?.query?.variables

    useEffect(() => {
        if (queryModalOpen && query) {
            setQueryInput(query)
            setSourceQuery({
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: query,
                    variables: variables,
                },
                display: ChartDisplayType.ActionsLineGraph,
            })
            runQuery(query)
        }
    }, [queryModalOpen, query]) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <LemonModal
            isOpen={queryModalOpen}
            onClose={closeQueryModal}
            fullScreen
            simple
            hideCloseButton
            className="!bg-transparent !border-none !shadow-none"
        >
            <div
                className="flex flex-col m-4 h-[calc(100%-2rem)] rounded-lg border bg-bg-light overflow-hidden shadow-xl transition-[margin-right] duration-200"
                style={sidePanelOpen && sidePanelWidth ? { marginRight: sidePanelWidth + 16 } : undefined}
            >
                <div className="flex items-center justify-between px-4 py-2 border-b bg-bg-light">
                    <span className="font-semibold">{node?.name ?? 'Edit query'}</span>
                    <div className="flex items-center gap-1">
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={() => {
                                if (savedQuery && queryInput) {
                                    updateView({
                                        id: savedQuery.id,
                                        query: { kind: NodeKind.HogQLQuery, query: queryInput, variables },
                                        types: [],
                                        shouldRematerialize: savedQuery.is_materialized ?? false,
                                        edited_history_id: savedQuery.latest_history_id,
                                    })
                                }
                            }}
                            disabledReason={
                                !savedQuery ? 'No saved query' : queryInput === query ? 'No changes to save' : undefined
                            }
                        >
                            Save
                        </LemonButton>
                        <LemonButton icon={<IconX />} size="small" onClick={closeQueryModal} />
                    </div>
                </div>
                <div className="flex-1 overflow-hidden">
                    <SQLEditor tabId={sqlEditorTabId} mode={SQLEditorMode.Embedded} />
                </div>
            </div>
        </LemonModal>
    )
}
