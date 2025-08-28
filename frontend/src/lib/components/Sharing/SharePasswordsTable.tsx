import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCopy, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { sharePasswordsLogic } from './sharePasswordsLogic'
import type { SharePassword } from './sharePasswordsLogic'

interface SharePasswordsTableProps {
    dashboardId?: number
    insightShortId?: string
    recordingId?: string
}

export function SharePasswordsTable({
    dashboardId,
    insightShortId,
    recordingId,
}: SharePasswordsTableProps): JSX.Element {
    const logicProps = { dashboardId, insightShortId, recordingId }
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
        <div>
            {/* Header section with minimal separation */}
            <div className="flex items-center justify-between mt-4 mb-2">
                <span className="text-xs text-muted-alt uppercase tracking-wide font-semibold">Passwords</span>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconPlus />}
                    onClick={() => setNewPasswordModalOpen(true)}
                    tooltip="Add a new password"
                >
                    Add
                </LemonButton>
            </div>

            {/* Password list - no container, just dividers */}
            {sharePasswordsLoading ? (
                <div className="py-3 text-center text-muted-alt text-sm">Loading passwords...</div>
            ) : sharePasswords.length === 0 ? (
                <div className="py-3 text-center border-t border-border">
                    <div className="text-muted-alt text-sm">No passwords created yet</div>
                </div>
            ) : (
                <div className="border-t border-border">
                    {sharePasswords.map((password) => (
                        <div
                            key={password.id}
                            className="group flex items-start justify-between gap-2 py-2.5 border-b border-border hover:bg-bg-light -mx-3 px-3"
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 text-xs text-muted mb-0.5">
                                    <span className="truncate">{password.created_by_email}</span>
                                    <span>•</span>
                                    <span className="whitespace-nowrap">
                                        {humanFriendlyDetailedTime(password.created_at)}
                                    </span>
                                </div>
                                <div className="text-sm">{password.note || 'No description'}</div>
                            </div>
                            <LemonButton
                                icon={<IconTrash />}
                                size="xsmall"
                                status="stealth"
                                className="opacity-0 group-hover:opacity-100 transition-opacity"
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
                    ))}
                </div>
            )}

            <LemonModal
                isOpen={newPasswordModalOpen}
                onClose={handleCloseModal}
                title="Create new share password"
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
                                        {dashboardId ? 'dashboard' : insightShortId ? 'insight' : 'recording'}.
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
        </div>
    )
}
