import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { passkeySettingsLogic } from './passkeySettingsLogic'
import { QuillPasskeyModals } from './QuillPasskeyModals'

export function PasskeyModals(): JSX.Element {
    const { deleteModalId, renameModal } = useValues(passkeySettingsLogic)
    const { closeDeleteModal, deletePasskey, closeRenameModal, renamePasskey } = useActions(passkeySettingsLogic)

    const [renameLabel, setRenameLabel] = useState('')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        if (renameModal) {
            setRenameLabel(renameModal.currentLabel)
        }
    }, [renameModal])

    const handleRename = (): void => {
        if (renameModal && renameLabel.trim()) {
            renamePasskey(renameModal.id, renameLabel.trim())
        }
    }

    const handleDelete = (): void => {
        if (deleteModalId) {
            deletePasskey(deleteModalId)
        }
    }

    if (todayRailNav) {
        return (
            <QuillPasskeyModals
                renameLabel={renameLabel}
                onRenameLabelChange={setRenameLabel}
                onRename={handleRename}
                onDelete={handleDelete}
            />
        )
    }

    return (
        <>
            <LemonModal
                isOpen={deleteModalId !== null}
                onClose={closeDeleteModal}
                title="Delete passkey?"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeDeleteModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" status="danger" onClick={handleDelete}>
                            Delete
                        </LemonButton>
                    </>
                }
            >
                <p>Are you sure you want to delete this passkey? You won't be able to use it to sign in anymore.</p>
            </LemonModal>

            <LemonModal
                isOpen={renameModal !== null}
                onClose={closeRenameModal}
                title="Rename passkey"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeRenameModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleRename}
                            disabledReason={!renameLabel.trim() ? 'Name is required' : undefined}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            >
                <LemonInput
                    value={renameLabel}
                    onChange={setRenameLabel}
                    placeholder="Passkey name"
                    autoFocus
                    onPressEnter={handleRename}
                    maxLength={200}
                />
            </LemonModal>
        </>
    )
}
