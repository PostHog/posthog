import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCopy, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { sharePasswordsLogic } from './sharePasswordsLogic'

interface SharePasswordsTableProps {
    dashboardId?: number
    insightId?: number
    recordingId?: string
}

// Export a hook to get password count for the parent component
export function useSharePasswordCount(props: SharePasswordsTableProps): number {
    const logic = sharePasswordsLogic(props)
    const { sharePasswords } = useValues(logic)
    return sharePasswords.length
}

export function SharePasswordsTable({ dashboardId, insightId, recordingId }: SharePasswordsTableProps): JSX.Element {
    const logicProps = { dashboardId, insightId, recordingId }
    const logic = sharePasswordsLogic(logicProps)

    const values = useValues(logic)

    const { sharePasswords, sharePasswordsLoading, newPasswordModalOpen, isCreatingPassword, createdPasswordResult } =
        values
    const { setNewPasswordModalOpen, createPassword, deletePassword, loadSharePasswords, clearCreatedPasswordResult } =
        useActions(sharePasswordsLogic(logicProps))
    const [newPasswordData, setNewPasswordData] = useState({ password: '', note: '' })

    // Load passwords when component mounts
    useEffect(() => {
        loadSharePasswords()
    }, [loadSharePasswords])

    const handleCreatePassword = async (): Promise<void> => {
        await createPassword(newPasswordData.password || undefined, newPasswordData.note || undefined)
        // Reset form data on success - the Kea logic will handle setting createdPasswordResult
        setNewPasswordData({ password: '', note: '' })
    }

    const handleCloseModal = (): void => {
        setNewPasswordModalOpen(false)
        clearCreatedPasswordResult()
        setNewPasswordData({ password: '', note: '' })
    }

    return (
        <>
            {sharePasswordsLoading ? (
                <div className="py-3 text-center text-muted-alt text-sm">Loading passwords...</div>
            ) : (
                <div className="w-full">
                    <div className="mx-1 h-px bg-border mb-3" />

                    <div className="mx-2">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-muted uppercase font-semibold">
                                {sharePasswords.length === 0
                                    ? 'No passwords'
                                    : `${sharePasswords.length} active ${sharePasswords.length === 1 ? 'password' : 'passwords'}`}
                            </span>
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                icon={<IconPlus />}
                                onClick={() => setNewPasswordModalOpen(true)}
                            >
                                Add
                            </LemonButton>
                        </div>

                        {sharePasswords.length === 0 ? (
                            <div className="py-3 text-muted-alt text-sm">Add a password to enable authentication</div>
                        ) : (
                            <div className="space-y-1 overflow-y-auto overflow-x-hidden" style={{ maxHeight: '280px' }}>
                                {sharePasswords.map((password) => (
                                    <div
                                        key={password.id}
                                        className="group flex items-start gap-3 py-2 hover:bg-bg-light rounded"
                                    >
                                        <div className="flex-1 min-w-0 overflow-hidden">
                                            <div className="text-sm font-medium break-words">
                                                {password.note || 'Untitled password'}
                                            </div>
                                            <div className="text-xs text-muted mt-0.5 break-words">
                                                <span>Created by: </span>
                                                <span className="break-all">{password.created_by_email}</span>
                                                <span className="mx-1">•</span>
                                                <span className="whitespace-nowrap">
                                                    {humanFriendlyDetailedTime(password.created_at)}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="flex-shrink-0">
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="xsmall"
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Remove password?',
                                                        description: password.note
                                                            ? `Remove the password "${password.note}"? Anyone using this password will lose access immediately.`
                                                            : 'Remove this password? Anyone using it will lose access immediately.',
                                                        primaryButton: {
                                                            children: 'Remove',
                                                            status: 'danger',
                                                            onClick: () => deletePassword(password.id),
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                        },
                                                    })
                                                }}
                                                tooltip="Remove password"
                                                tooltipPlacement="left"
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}

            <LemonModal
                isOpen={newPasswordModalOpen}
                onClose={handleCloseModal}
                title="Create new share password"
                width={480}
                footer={
                    createdPasswordResult ? (
                        <LemonButton type="primary" onClick={handleCloseModal}>
                            Done
                        </LemonButton>
                    ) : (
                        <>
                            <LemonButton type="secondary" onClick={handleCloseModal}>
                                Cancel
                            </LemonButton>
                            <LemonButton type="primary" onClick={handleCreatePassword} loading={isCreatingPassword}>
                                Create password
                            </LemonButton>
                        </>
                    )
                }
            >
                {createdPasswordResult ? (
                    <div className="space-y-4">
                        <div>
                            <div className="text-sm text-muted mb-3">
                                Save this password - it won't be shown again for security reasons.
                            </div>
                            <div className="rounded bg-bg-3000 border border-border p-3">
                                <div className="flex items-center justify-between gap-2">
                                    <div className="flex-1 overflow-hidden">
                                        <div className="text-xs text-muted-alt uppercase tracking-wide font-semibold mb-1">
                                            Password
                                        </div>
                                        <div className="font-mono text-sm text-default break-all select-all bg-white dark:bg-gray-900 px-2 py-1.5 rounded border border-border">
                                            {createdPasswordResult.password}
                                        </div>
                                    </div>
                                    <div className="flex-shrink-0">
                                        <LemonButton
                                            icon={<IconCopy />}
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                copyToClipboard(createdPasswordResult.password, 'password')
                                            }}
                                            tooltip="Copy to clipboard"
                                        />
                                    </div>
                                </div>
                                {createdPasswordResult.note && (
                                    <div className="mt-3 pt-3 border-t border-border">
                                        <div className="text-xs text-muted">Note</div>
                                        <div className="text-sm mt-0.5">{createdPasswordResult.note}</div>
                                    </div>
                                )}
                            </div>
                            <div className="mt-3 p-3 bg-warning-highlight border border-warning rounded">
                                <div className="flex gap-2">
                                    <IconWarning className="text-warning text-lg flex-shrink-0 mt-0.5" />
                                    <div className="text-sm">
                                        <strong>Important:</strong> Store this password securely. Anyone with this
                                        password will be able to access this{' '}
                                        {dashboardId ? 'dashboard' : insightId ? 'insight' : 'recording'}.
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium mb-2">Password (optional)</label>
                            <LemonInput
                                type="password"
                                placeholder="Leave empty to generate a random password"
                                value={newPasswordData.password}
                                onChange={(value) => setNewPasswordData((prev) => ({ ...prev, password: value }))}
                            />
                            <div className="text-xs text-muted mt-1">
                                If left empty, a secure random password will be generated for you.
                            </div>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-2">Note (optional)</label>
                            <LemonInput
                                placeholder="e.g., For marketing team, External client access..."
                                value={newPasswordData.note}
                                onChange={(value) => setNewPasswordData((prev) => ({ ...prev, note: value }))}
                                maxLength={100}
                            />
                            <div className="text-xs text-muted mt-1">
                                Add a note to help identify this password later.
                            </div>
                        </div>
                    </div>
                )}
            </LemonModal>
        </>
    )
}
