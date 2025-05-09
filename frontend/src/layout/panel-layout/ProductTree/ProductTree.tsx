import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'

export function ProductTree(): JSX.Element {
    const { treeItemsProducts } = useValues(projectTreeLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

    return (
        <PanelLayoutPanel>
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeItemsProducts}
                onFolderClick={(folder) => {
                    if (folder?.id) {
                        if (expandedFolders.includes(folder.id)) {
                            setExpandedFolders(expandedFolders.filter((id) => id !== folder.id))
                        } else {
                            setExpandedFolders([...expandedFolders, folder.id])
                        }
                    }
                }}
                onItemClick={(node) => {
                    if (node?.record?.href) {
                        router.actions.push(
                            typeof node.record.href === 'function'
                                ? node.record.href(node.record.ref)
                                : node.record.href
                        )
                    }
                    node?.onClick?.(true)
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
            />
        </PanelLayoutPanel>
    )
}
