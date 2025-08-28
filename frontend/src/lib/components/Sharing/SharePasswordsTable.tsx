import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'

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

    const columns = [
        {
            title: 'Created',
            dataIndex: 'created_at' as keyof SharePassword,
            render: (created_at: string) => humanFriendlyDetailedTime(created_at),
            sorter: (a: SharePassword, b: SharePassword) =>
                new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
        },
        {
            title: 'Creator',
            dataIndex: 'created_by_email' as keyof SharePassword,
            render: (email: string) => email,
        },
        {
            title: 'Note',
            dataIndex: 'note' as keyof SharePassword,
            render: (note: string) => note || <span className="text-muted">No note</span>,
        },
        {
            title: 'Actions',
            key: 'actions',
            render: (_: any, password: SharePassword) => (
                <LemonButton
                    icon={<IconTrash />}
                    status="danger"
                    size="small"
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Delete password?',
                            description:
                                `Are you sure you want to delete this share password${password.note ? ` (${password.note})` : ''}? ` +
                                'Anyone using this password will lose access immediately.',
                            primaryButton: {
                                children: 'Delete password',
                                status: 'danger',
                                onClick: () => deletePassword(password.id),
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    }}
                    tooltip="Delete this password"
                    tooltipPlacement="left"
                />
            ),
        },
    ]

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="mb-0">Share passwords</h4>
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => setNewPasswordModalOpen(true)}
                >
                    Create new password
                </LemonButton>
            </div>

            <LemonTable
                columns={columns}
                dataSource={sharePasswords}
                loading={sharePasswordsLoading}
                size="small"
                pagination={false}
                emptyState="No passwords created yet"
            />

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
                        <div className="bg-success-highlight border border-success rounded p-4">
                            <h4 className="text-success mb-2">Password created successfully!</h4>
                            <p className="mb-3">
                                Copy this password now - it won't be shown again for security reasons.
                            </p>
                            <div className="flex items-center space-x-2">
                                <LemonInput
                                    value={createdPasswordResult.password}
                                    readOnly
                                    type="text"
                                    className="font-mono"
                                />
                                <LemonButton
                                    icon={<IconCopy />}
                                    onClick={() => {
                                        copyToClipboard(createdPasswordResult.password, 'share password')
                                    }}
                                />
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
