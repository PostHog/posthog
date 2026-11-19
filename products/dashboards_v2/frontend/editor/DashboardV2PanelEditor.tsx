import { useActions, useValues } from 'kea'

import { newPanel } from '../explore/build'
import { editorFor, useEditorPref } from '../lib/editor'
import type { Panel } from '../spec'
import { ConfirmHost } from './Confirm'
import { useDisplay } from './display'
import { PanelPopup } from './PanelEditor'
import { panelEditorChoiceLogic } from './panelEditorChoiceLogic'
import { panelEditorLogic } from './panelEditorLogic'
import { AddTileGallery, SimpleTileEditor } from './SimpleEditor'

export function DashboardV2PanelEditor(): JSX.Element {
    const { openPanelId, openPanelMode, draft, panelLayout } = useValues(panelEditorLogic)
    const { openPanel, closePanel, setDraft, setPanelLayout, duplicatePanel, confirmRemovePanel, addPanel } =
        useActions(panelEditorLogic)
    const { galleryOpen, forceAdvanced } = useValues(panelEditorChoiceLogic)
    const { setGalleryOpen, setForceAdvanced } = useActions(panelEditorChoiceLogic)
    const editor = editorFor(useEditorPref(), useDisplay())
    const simple = editor === 'simple' && openPanelMode === 'edit' && !forceAdvanced

    const close = (): void => {
        setForceAdvanced(false)
        closePanel()
    }

    return (
        <>
            {openPanelId &&
                openPanelMode &&
                draft &&
                (simple ? (
                    <SimpleTileEditor
                        key={openPanelId}
                        id={openPanelId}
                        panel={draft as Panel}
                        onChange={(next) => setDraft(next, openPanelId)}
                        onClose={close}
                        onAdvanced={() => setForceAdvanced(true)}
                    />
                ) : (
                    <PanelPopup
                        key={openPanelId}
                        id={openPanelId}
                        panel={draft as Panel}
                        mode={openPanelMode}
                        layout={panelLayout}
                        canEdit
                        onMode={(mode) => openPanel(openPanelId, mode)}
                        onLayout={setPanelLayout}
                        onClose={close}
                        onChange={(next) => setDraft(next, openPanelId)}
                        onDuplicate={duplicatePanel}
                        onRemove={confirmRemovePanel}
                    />
                ))}
            {galleryOpen && (
                <AddTileGallery
                    onAdd={(panel) => {
                        setGalleryOpen(false)
                        addPanel(panel)
                    }}
                    onAdvanced={() => {
                        setGalleryOpen(false)
                        setForceAdvanced(true)
                        addPanel(newPanel())
                    }}
                    onClose={() => setGalleryOpen(false)}
                />
            )}
            <ConfirmHost />
        </>
    )
}
