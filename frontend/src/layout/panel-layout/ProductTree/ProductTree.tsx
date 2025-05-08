import { useValues } from 'kea'
import { LemonTree, LemonTreeRef } from 'lib/lemon-ui/LemonTree/LemonTree'
import { RefObject, useRef, useState } from 'react'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { PanelLayoutPanel } from '../PanelLayoutPanel'
import { projectTreeLogic } from '../ProjectTree/projectTreeLogic'

export function ProductTree(): JSX.Element {
    const { treeItemsAllProducts } = useValues(projectTreeLogic)
    const { mainContentRef } = useValues(panelLayoutLogic)

    const treeRef = useRef<LemonTreeRef>(null)
    const [expandedFolders, setExpandedFolders] = useState<string[]>(['/'])

    return (
        <PanelLayoutPanel>
            <LemonTree
                ref={treeRef}
                contentRef={mainContentRef as RefObject<HTMLElement>}
                className="px-0 py-1"
                data={treeItemsAllProducts}
                onFolderClick={(folder) => {
                    if (folder?.id) {
                        if (expandedFolders.includes(folder.id)) {
                            setExpandedFolders(expandedFolders.filter((id) => id !== folder.id))
                        } else {
                            setExpandedFolders([...expandedFolders, folder.id])
                        }
                    }
                }}
                onNodeClick={(node) => {
                    node?.onClick?.(true)
                }}
                expandedItemIds={expandedFolders}
                onSetExpandedItemIds={setExpandedFolders}
            />
        </PanelLayoutPanel>
    )
}
