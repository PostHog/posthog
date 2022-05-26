import React, { useState, useRef, useCallback, Dispatch, SetStateAction } from 'react'
import { Table, Modal, Input, Alert, Popconfirm } from 'antd'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import { PersonalAPIKeyType } from '~/types'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { CopyToClipboardInline } from '../CopyToClipboard'
import { ColumnsType } from 'antd/lib/table'
import { LemonButton } from '../LemonButton'

function CreateKeyModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createKey } = useActions(personalAPIKeysLogic)

    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const inputRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsVisible(false)
        if (inputRef.current) {
            inputRef.current.setValue('')
        }
    }, [inputRef, setIsVisible])

    return (
        <Modal
            title="Creating a Personal API Key"
            okText="Create Key"
            cancelText="Cancel"
            onOk={() => {
                const label = inputRef.current?.state.value?.trim()
                if (label) {
                    setErrorMessage(null)
                    createKey(label)
                    closeModal()
                } else {
                    setErrorMessage('Your key needs a label!')
                }
            }}
            onCancel={closeModal}
            visible={isVisible}
        >
            <Input
                addonBefore="Label"
                ref={inputRef}
                placeholder='for example "Zapier"'
                maxLength={40}
                style={{ marginBottom: '1rem' }}
            />
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginBottom: '1rem' }} />}
            <p style={{ marginBottom: 0 }}>
                Key value <b>will only ever be shown once</b>, immediately after creation.
                <br />
                Copy it to your destination right away.
            </p>
        </Modal>
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
                <a className="text-danger">Delete</a>
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
            render: (lastUsedAt: string | null) => humanFriendlyDetailedTime(lastUsedAt),
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
    const [isCreateKeyModalVisible, setIsCreateKeyModalVisible] = useState(false)

    return (
        <>
            <p>
                These keys allow full access to your personal account through the API, as if you were logged in. You can
                also use them in integrations, such as{' '}
                <a href="https://zapier.com/apps/posthog/">our premium Zapier one</a>.
                <br />
                Try not to keep disused keys around. If you have any suspicion that one of these may be compromised,
                delete it and use a new one.
                <br />
                <a href="https://posthog.com/docs/api/overview#authentication">
                    More about API authentication in PostHog Docs.
                </a>
            </p>
            <LemonButton
                type="primary"
                onClick={() => {
                    setIsCreateKeyModalVisible(true)
                }}
            >
                + Create personal API key
            </LemonButton>
            <CreateKeyModal isVisible={isCreateKeyModalVisible} setIsVisible={setIsCreateKeyModalVisible} />
            <PersonalAPIKeysTable />
        </>
    )
}
