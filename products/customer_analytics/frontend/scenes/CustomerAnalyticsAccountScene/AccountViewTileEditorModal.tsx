import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { accountViewsLogic } from './accountViewsLogic'

interface AccountViewTileEditorModalProps {
    projectId: number
}

export function AccountViewTileEditorModal({ projectId }: AccountViewTileEditorModalProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { tileEditor, tileSaving } = useValues(logic)
    const { closeTileEditor, saveTileEditor, setTileEditorName } = useActions(logic)
    const saveDisabledReason = tileSaving
        ? 'Saving changes'
        : !tileEditor?.name.trim()
          ? 'Enter a tile name'
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
                    onChange={setTileEditorName}
                    onPressEnter={tileSaving ? undefined : saveTileEditor}
                    autoFocus
                    maxLength={400}
                    data-attr="account-view-tile-name"
                />
            </div>
        </LemonModal>
    )
}
