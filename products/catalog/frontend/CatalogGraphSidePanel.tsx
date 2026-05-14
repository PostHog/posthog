import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExpand45, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { CatalogDefinitionForm, CatalogDefinitionFormActions } from './CatalogDefinitionForm'
import { catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'
import { catalogGraphSceneLogic } from './catalogGraphSceneLogic'

export function CatalogGraphSidePanel(): JSX.Element | null {
    const { selectedNodeId } = useValues(catalogGraphSceneLogic)

    if (!selectedNodeId) {
        return null
    }

    return (
        <BindLogic logic={catalogDefinitionSceneLogic} props={{ id: selectedNodeId }}>
            <CatalogGraphSidePanelContent selectedNodeId={selectedNodeId} />
        </BindLogic>
    )
}

function CatalogGraphSidePanelContent({ selectedNodeId }: { selectedNodeId: string }): JSX.Element {
    const { graph } = useValues(catalogGraphSceneLogic)
    const { setSelectedNodeId, replaceGraphNode } = useActions(catalogGraphSceneLogic)
    const { definition } = useValues(catalogDefinitionSceneLogic)

    // Mirror the bound logic's definition back into the graph state so the canvas
    // card and the panel header reflect saves immediately, with no page refresh.
    useEffect(() => {
        if (definition && definition.id === selectedNodeId) {
            replaceGraphNode(definition)
        }
    }, [definition, replaceGraphNode, selectedNodeId])

    // Fall back to the snapshot from the graph payload while the retrieve call is in flight.
    const header = definition ?? graph?.nodes.find((n) => n.id === selectedNodeId) ?? null

    return (
        <div
            className="absolute top-2 right-2 bottom-2 w-[520px] flex flex-col rounded-md overflow-hidden bg-surface-primary z-10"
            style={{ border: '1px solid var(--border)', boxShadow: '0 3px 0 var(--border)' }}
        >
            <div className="flex items-center gap-2 px-3 py-2 border-b">
                <span className="font-mono text-sm truncate flex-1" title={header?.name}>
                    {header?.name ?? 'Loading…'}
                </span>
                {header && (
                    <LemonTag type={STATUS_COLOR[header.status] ?? 'default'}>
                        {STATUS_LABEL[header.status] ?? header.status}
                    </LemonTag>
                )}
                <LemonButton
                    size="small"
                    icon={<IconExpand45 />}
                    to={urls.catalogDefinition(selectedNodeId)}
                    tooltip="Open full detail page"
                />
                <LemonButton size="small" icon={<IconX />} onClick={() => setSelectedNodeId(null)} tooltip="Close" />
            </div>
            <div className="flex-1 overflow-y-auto p-3">
                <CatalogDefinitionForm compact hideActions />
            </div>
            <div className="border-t px-3 py-2 bg-surface-primary">
                <CatalogDefinitionFormActions />
            </div>
        </div>
    )
}
