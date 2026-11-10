import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { getAccountViewComponentByKind } from '../../components/Accounts/accountViewComponents'
import { accountViewsLogic } from './accountViewsLogic'

interface AccountViewTileEditorModalProps {
    projectId: number
}

export function AccountViewTileEditorModal({ projectId }: AccountViewTileEditorModalProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { tileEditor, tileSaving } = useValues(logic)
    const { closeTileEditor, saveTileEditor, setTileEditorName, setTileEditorConfig } = useActions(logic)
    const definition = tileEditor?.kind ? getAccountViewComponentByKind(tileEditor.kind) : undefined
    const ConfigEditor = definition?.ConfigEditor
    const saveDisabledReason = tileSaving
        ? 'Saving changes'
        : !tileEditor?.name.trim()
          ? 'Enter a tile name'
          : tileEditor?.config
            ? definition?.getConfigError?.(tileEditor.config)
            : undefined

    return (
        <LemonModal
            isOpen={tileEditor !== null}
            onClose={() => {
                if (!tileSaving) {
                    closeTileEditor()
                }
            }}
            title="Edit tile"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeTileEditor}
                        disabledReason={tileSaving ? 'Saving changes' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveTileEditor}
                        loading={tileSaving}
                        disabledReason={saveDisabledReason}
                        data-attr="account-view-tile-save"
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor="account-view-tile-name">Tile name</LemonLabel>
                <LemonInput
                    id="account-view-tile-name"
                    value={tileEditor?.name ?? ''}
                    disabled={tileSaving}
                    onChange={setTileEditorName}
                    onPressEnter={tileSaving || saveDisabledReason ? undefined : saveTileEditor}
                    autoFocus
                    maxLength={400}
                    data-attr="account-view-tile-name"
                />
            </div>
            {ConfigEditor && tileEditor?.config && tileEditor.accountId ? (
                <div className="mt-4">
                    <ConfigEditor
                        projectId={projectId}
                        accountId={tileEditor.accountId}
                        config={tileEditor.config}
                        saving={tileSaving}
                        onChange={setTileEditorConfig}
                    />
                </div>
            ) : null}
        </LemonModal>
    )
}
