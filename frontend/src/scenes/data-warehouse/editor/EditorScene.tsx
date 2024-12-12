import { IconArrowLeft } from '@posthog/icons'
import { BindLogic, useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { DatabaseTableTree } from 'lib/components/DatabaseTableTree/DatabaseTableTree'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useRef } from 'react'

import { Sidebar } from '~/layout/navigation-3000/components/Sidebar'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'

import { ViewLinkModal } from '../ViewLinkModal'
import { editorSceneLogic } from './editorSceneLogic'
import { editorSizingLogic } from './editorSizingLogic'
import { QueryWindow } from './QueryWindow'

export function EditorScene(): JSX.Element {
    const ref = useRef(null)
    const navigatorRef = useRef(null)
    const queryPaneRef = useRef(null)
    const { activeNavbarItem } = useValues(navigation3000Logic)
    const { sidebarOverlayOpen } = useValues(editorSceneLogic)

    const editorSizingLogicProps = {
        editorSceneRef: ref,
        navigatorRef,
        sourceNavigatorResizerProps: {
            containerRef: navigatorRef,
            logicKey: 'source-navigator',
            placement: 'right',
        },
        queryPaneResizerProps: {
            containerRef: queryPaneRef,
            logicKey: 'query-pane',
            placement: 'bottom',
        },
    }

    return (
        <BindLogic logic={editorSizingLogic} props={editorSizingLogicProps}>
            <div className="w-full h-full flex flex-row overflow-hidden" ref={ref}>
                {activeNavbarItem && (
                    <Sidebar
                        key={activeNavbarItem.identifier}
                        navbarItem={activeNavbarItem}
                        sidebarOverlay={<EditorSidebarOverlay />}
                        sidebarOverlayProps={{ isOpen: sidebarOverlayOpen }}
                    />
                )}
                <QueryWindow />
            </div>
            <ViewLinkModal />
        </BindLogic>
    )
}

const EditorSidebarOverlay = (): JSX.Element => {
    const { setSidebarOverlayOpen } = useActions(editorSceneLogic)
    const { sidebarOverlayTreeItems, selectedSchema } = useValues(editorSceneLogic)

    return (
        <div className="flex flex-col">
            <header className="flex flex-row h-10 border-b shrink-0 p-1 gap-2">
                <LemonButton size="small" icon={<IconArrowLeft />} onClick={() => setSidebarOverlayOpen(false)} />
                {selectedSchema?.name && (
                    <CopyToClipboardInline
                        className="font-mono"
                        tooltipMessage={null}
                        description="schema"
                        iconStyle={{ color: 'var(--muted-alt)' }}
                        explicitValue={selectedSchema?.name}
                    >
                        {selectedSchema?.name}
                    </CopyToClipboardInline>
                )}
            </header>
            <DatabaseTableTree items={sidebarOverlayTreeItems} />
        </div>
    )
}
