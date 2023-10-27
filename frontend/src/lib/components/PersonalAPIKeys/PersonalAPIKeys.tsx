import { useState, useCallback, Dispatch, SetStateAction } from 'react'
import { Table, Popconfirm } from 'antd'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import { PersonalAPIKeyType } from '~/types'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { CopyToClipboardInline } from '../CopyToClipboard'
import { ColumnsType } from 'antd/lib/table'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput, LemonModal, Link } from '@posthog/lemon-ui'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { IconPlus } from 'lib/lemon-ui/icons'

function CreateKeyModal({
    isOpen,
    setIsOpen,
}: {
    isOpen: boolean
    setIsOpen: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createKey } = useActions(personalAPIKeysLogic)

    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [label, setLabel] = useState('')

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsOpen(false)
    }, [setIsOpen])

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

function RowValue(value: string): JSX.Element {
    return value ? (
        <CopyToClipboardInline description="personal API key value">{value}</CopyToClipboardInline>
    ) : (
        <i>secret</i>
    )
}

function RowActionsCreator(
    deleteKey: (key: PersonalAPIKeyType) => void
): (personalAPIKey: PersonalAPIKeyType) => JSX.Element {
    return function RowActions(personalAPIKey: PersonalAPIKeyType) {
        return (
            <Popconfirm
                title={`Permanently delete key "${personalAPIKey.label}"?`}
                okText="Delete Key"
                okType="danger"
                icon={<ExclamationCircleOutlined style={{ color: 'var(--danger)' }} />}
                placement="left"
                onConfirm={() => {
                    deleteKey(personalAPIKey)
                }}
            >
                <span className="text-danger">Danger</span>
            </Popconfirm>
        )
    }
}

function PersonalAPIKeysTable(): JSX.Element {
    const { keys } = useValues(personalAPIKeysLogic) as { keys: PersonalAPIKeyType[] }
    const { deleteKey } = useActions(personalAPIKeysLogic)

    const columns: ColumnsType<Record<string, any>> = [
        {
            title: 'Label',
            dataIndex: 'label',
            key: 'label',
        },
        {
            title: 'Value',
            dataIndex: 'value',
            key: 'value',
            className: 'ph-no-capture',
            render: RowValue,
        },
        {
            title: 'Last Used',
            dataIndex: 'last_used_at',
            key: 'lastUsedAt',
            render: (lastUsedAt: string | null) => humanFriendlyDetailedTime(lastUsedAt, 'MMMM DD, YYYY', 'h A'),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'createdAt',
            render: (createdAt: string | null) => humanFriendlyDetailedTime(createdAt),
        },
        {
            title: '',
            key: 'actions',
            align: 'center',
            render: RowActionsCreator(deleteKey),
        },
    ]

    return (
        <Table
            dataSource={keys}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 50, hideOnSinglePage: true }}
            style={{ marginTop: '1rem' }}
        />
    )
}

export function PersonalAPIKeys(): JSX.Element {
    const [modalIsOpen, setModalIsOpen] = useState(false)

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
                    setModalIsOpen(true)
                }}
                icon={<IconPlus />}
            >
                Create personal API key
            </LemonButton>
            <CreateKeyModal isOpen={modalIsOpen} setIsOpen={setModalIsOpen} />
            <PersonalAPIKeysTable />
        </>
    )
}
