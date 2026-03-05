import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { NodeDetailLineageFullscreen } from './NodeDetailLineage'
import { nodeDetailSceneLogic, NodeDetailSceneLogicProps } from './nodeDetailSceneLogic'

export function NodeDetailLineageModal({ id }: NodeDetailSceneLogicProps): JSX.Element {
    const logicProps = { id }
    const { lineageModalOpen, node } = useValues(nodeDetailSceneLogic(logicProps))
    const { closeLineageModal } = useActions(nodeDetailSceneLogic(logicProps))
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { sidePanelWidth } = useValues(panelLayoutLogic)

    return (
        <LemonModal
            isOpen={lineageModalOpen}
            onClose={closeLineageModal}
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
                    <span className="font-semibold">{node?.name ? `${node.name} — Lineage` : 'Lineage'}</span>
                    <LemonButton icon={<IconX />} size="small" onClick={closeLineageModal} />
                </div>
                <div className="flex-1 overflow-hidden">
                    <NodeDetailLineageFullscreen id={id} />
                </div>
            </div>
        </LemonModal>
    )
}
