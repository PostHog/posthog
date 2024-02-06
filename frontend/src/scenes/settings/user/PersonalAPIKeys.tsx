import { LemonDialog, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useCallback, useEffect, useState } from 'react'

import { PersonalAPIKeyType } from '~/types'

import { CopyToClipboardInline } from '../../../lib/components/CopyToClipboard'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'

function EditKeyModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { createKey } = useActions(personalAPIKeysLogic)

    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [label, setLabel] = useState('')

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        onClose()
    }, [onClose])

    return (
        <LemonModal
            title="Creating a Personal API Key"
            onClose={closeModal}
            isOpen={isOpen}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>

                    <LemonButton
                        type="primary"
                        onClick={() => {
                            if (label) {
                                setErrorMessage(null)
                                createKey(label)
                                setLabel('')
                                closeModal()
                            } else {
                                setErrorMessage('Your key needs a label!')
                            }
                        }}
                    >
                        Create key
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput placeholder='for example "Zapier"' maxLength={40} onChange={setLabel} value={label} />
                {errorMessage && <LemonBanner type="error">{errorMessage}</LemonBanner>}
                <p>
                    Key value <b>will only ever be shown once</b>, immediately after creation.
                    <br />
                    Copy it to your destination right away.
                </p>
            </div>
        </LemonModal>
    )
}

function PersonalAPIKeysTable(): JSX.Element {
    const { keys } = useValues(personalAPIKeysLogic) as { keys: PersonalAPIKeyType[] }
    const { deleteKey, loadKeys } = useActions(personalAPIKeysLogic)

    useEffect(() => loadKeys(), [])

    return (
        <LemonTable
            dataSource={keys}
            className="mt-4"
            columns={[
                {
                    title: 'Label',
                    dataIndex: 'label',
                    key: 'label',
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                    render: function RenderValue(value) {
                        return value ? (
                            <CopyToClipboardInline description="personal API key value">
                                {String(value)}
                            </CopyToClipboardInline>
                        ) : (
                            <i>secret</i>
                        )
                    },
                },
                {
                    title: 'Last Used',
                    dataIndex: 'last_used_at',
                    key: 'lastUsedAt',
                    render: (_, key) => humanFriendlyDetailedTime(key.last_used_at, 'MMMM DD, YYYY', 'h A'),
                },
                {
                    title: 'Created',
                    dataIndex: 'created_at',
                    key: 'createdAt',
                    render: (_, key) => humanFriendlyDetailedTime(key.created_at),
                },
                {
                    title: '',
                    key: 'actions',
                    align: 'right',
                    width: 0,
                    render: (_, key) => {
                        return (
                            <LemonButton
                                status="danger"
                                type="tertiary"
                                size="xsmall"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: `Permanently delete key "${key.label}"?`,
                                        description:
                                            'This action cannot be undone. Make sure to have removed the key from any live integrations first.',
                                        primaryButton: {
                                            status: 'danger',
                                            children: 'Permanently delete',
                                            onClick: () => deleteKey(key.id),
                                        },
                                    })
                                }}
                            >
                                Delete
                            </LemonButton>
                        )
                    },
                },
            ]}
        />
    )
}

export function PersonalAPIKeys(): JSX.Element {
    const [editingId, setEditingId] = useState<string | null>(null)

    return (
        <>
            <p>
                These keys allow full access to your personal account through the API, as if you were logged in. You can
                also use them in integrations, such as{' '}
                <Link to="https://zapier.com/apps/posthog/">our premium Zapier one</Link>.
                <br />
                Try not to keep disused keys around. If you have any suspicion that one of these may be compromised,
                delete it and use a new one.
                <br />
                <Link to="https://posthog.com/docs/api/overview#authentication">
                    More about API authentication in PostHog Docs.
                </Link>
            </p>
            <LemonButton
                type="primary"
                onClick={() => {
                    setEditingId('new')
                }}
                icon={<IconPlus />}
            >
                Create personal API key
            </LemonButton>

            <PersonalAPIKeysTable />

            <EditKeyModal isOpen={!!editingId} onClose={() => setEditingId(null)} id={editingId} />
        </>
    )
}
