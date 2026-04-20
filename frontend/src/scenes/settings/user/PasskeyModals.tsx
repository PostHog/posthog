import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeyModals(): JSX.Element {
    const { deleteModalId, renameModal } = useValues(passkeySettingsLogic)
    const { closeDeleteModal, deletePasskey, closeRenameModal, renamePasskey } = useActions(passkeySettingsLogic)

    const [renameLabel, setRenameLabel] = useState('')

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
                        <LemonButton
                            type="primary"
                            status="danger"
                            onClick={() => deleteModalId && deletePasskey(deleteModalId)}
                        >
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
