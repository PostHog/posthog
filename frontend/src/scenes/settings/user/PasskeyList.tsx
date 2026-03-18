import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconChip, IconClock, IconLaptop, IconLock, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'

import { IconLink, IconSync } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { PasskeyCredential, passkeySettingsLogic } from './passkeySettingsLogic'

function VerificationStatusIcon({ verified, verifying }: { verified: boolean; verifying: boolean }): JSX.Element {
    if (verifying) {
        return <IconSync className="text-warning animate-spin" />
    }
    if (verified) {
        return <IconCheckCircle className="text-success" />
    }
    return <IconClock className="text-muted" />
}

function AuthenticatorTypeIcon({ type }: { type: 'platform' | 'hardware' | 'hybrid' | 'unknown' }): JSX.Element {
    switch (type) {
        case 'hardware':
            return <IconChip className="text-muted" />
        case 'platform':
            return <IconLaptop className="text-muted" />
        case 'hybrid':
            return <IconLink className="text-muted" />
        default:
            return <IconLock className="text-muted" />
    }
}

function getAuthenticatorTypeText(type: 'platform' | 'hardware' | 'hybrid' | 'unknown'): string {
    switch (type) {
        case 'hardware':
            return 'Hardware'
        case 'platform':
            return 'Platform'
        case 'hybrid':
            return 'Hybrid'
        default:
            return 'Unknown'
    }
}

function getVerificationStatusText(verified: boolean, verifying: boolean): string {
    if (verifying) {
        return 'Verifying'
    }
    if (verified) {
        return 'Verified'
    }
    return 'Not verified'
}

export function PasskeyList(): JSX.Element {
    const { passkeys, passkeysLoading, verifyingPasskeyId } = useValues(passkeySettingsLogic)
    const { verifyPasskey, openDeleteModal, openRenameModal } = useActions(passkeySettingsLogic)

    if (passkeysLoading && passkeys.length === 0) {
        return (
            <div className="flex justify-center py-8">
                <Spinner />
            </div>
        )
    }

    return (
        <LemonTable
            dataSource={passkeys}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'label',
                    key: 'label',
                    render: (_, record: PasskeyCredential) => (
                        <div className="flex items-center gap-2">
                            <IconLock className="text-muted" />
                            <span className="font-medium">{record.label}</span>
                        </div>
                    ),
                },
                {
                    title: 'Type',
                    key: 'authenticator_type',
                    width: 120,
                    render: (_: any, record: PasskeyCredential) => (
                        <div className="flex items-center gap-2">
                            <AuthenticatorTypeIcon type={record.authenticator_type} />
                            <span className="text-sm">{getAuthenticatorTypeText(record.authenticator_type)}</span>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'verified',
                    width: 180,
                    render: (_: any, record: PasskeyCredential) => {
                        const verifying = verifyingPasskeyId === record.id
                        const statusText = getVerificationStatusText(record.verified, verifying)
                        return (
                            <div className="flex items-center gap-2">
                                <VerificationStatusIcon verified={record.verified} verifying={verifying} />
                                <span className="text-sm">{statusText}</span>
                                {!record.verified && !verifying && (
                                    <LemonButton
                                        size="small"
                                        onClick={() => verifyPasskey(record.id)}
                                        tooltip="Verify this passkey"
                                    >
                                        Verify
                                    </LemonButton>
                                )}
                            </div>
                        )
                    },
                },
                {
                    title: 'Added',
                    dataIndex: 'created_at',
                    key: 'created_at',
                    render: (_: any, record: PasskeyCredential) => humanFriendlyDetailedTime(record.created_at),
                },
                {
                    title: '',
                    key: 'actions',
                    width: 100,
                    render: (_: any, record: PasskeyCredential) => (
                        <div className="flex gap-1">
                            <LemonButton
                                icon={<IconPencil />}
                                size="small"
                                tooltip="Rename"
                                onClick={() => openRenameModal(record.id, record.label)}
                            />
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                status="danger"
                                tooltip="Delete"
                                onClick={() => openDeleteModal(record.id)}
                            />
                        </div>
                    ),
                },
            ]}
            loading={passkeysLoading}
            emptyState="No passkeys"
        />
    )
}
