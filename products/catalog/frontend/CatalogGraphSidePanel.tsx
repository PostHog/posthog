import { BindLogic, useActions, useValues } from 'kea'

import { IconExpand45, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { CatalogDefinitionForm } from './CatalogDefinitionForm'
import { catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'
import { catalogGraphSceneLogic } from './catalogGraphSceneLogic'

export function CatalogGraphSidePanel(): JSX.Element | null {
    const { selectedNodeId, graph } = useValues(catalogGraphSceneLogic)
    const { setSelectedNodeId } = useActions(catalogGraphSceneLogic)

    if (!selectedNodeId) {
        return null
    }

    // Look up the freshly-loaded node from the graph payload so the panel header
    // can show name and status before the definition loader inside the form
    // finishes its retrieve call.
    const selected = graph?.nodes.find((n) => n.id === selectedNodeId)

    return (
        <BindLogic logic={catalogDefinitionSceneLogic} props={{ id: selectedNodeId }}>
            <div
                className="absolute top-2 right-2 bottom-2 w-[520px] flex flex-col rounded-md overflow-hidden bg-surface-primary z-10"
                style={{ border: '1px solid var(--border)', boxShadow: '0 3px 0 var(--border)' }}
            >
                <div className="flex items-center gap-2 px-3 py-2 border-b">
                    <span className="font-mono text-sm truncate flex-1" title={selected?.name}>
                        {selected?.name ?? 'Loading…'}
                    </span>
                    {selected && (
                        <LemonTag type={STATUS_COLOR[selected.status] ?? 'default'}>
                            {STATUS_LABEL[selected.status] ?? selected.status}
                        </LemonTag>
                    )}
                    <LemonButton
                        size="small"
                        icon={<IconExpand45 />}
                        to={urls.catalogDefinition(selectedNodeId)}
                        tooltip="Open full detail page"
                    />
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        onClick={() => setSelectedNodeId(null)}
                        tooltip="Close"
                    />
                </div>
                <div className="flex-1 overflow-y-auto p-3">
                    <CatalogDefinitionForm compact />
                </div>
            </div>
        </BindLogic>
    )
}
