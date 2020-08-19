import React, { useState, useRef, useCallback, Dispatch, SetStateAction } from 'react'
import { Table, Modal, Button, Input, Alert, Popconfirm } from 'antd'
import { useActions, useValues } from 'kea'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { red } from '@ant-design/colors'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'
import { PersonalAPIKeyType } from '~/types'
import { humanFriendlyDetailedTime } from 'lib/utils'

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
        if (inputRef.current) inputRef.current.state.value = ''
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
                    createKey(inputRef.current?.state.value.trim())
                    closeModal()
                } else {
                    setErrorMessage('Your key needs a label!')
                }
            }}
            onCancel={closeModal}
            okK
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

function PersonalAPIKeysTable(): JSX.Element {
    const { keys } = useValues(personalAPIKeysLogic) as { keys: PersonalAPIKeyType[] }
    const { deleteKey } = useActions(personalAPIKeysLogic)

    function RowActions(_: string, personalAPIKey: PersonalAPIKeyType): JSX.Element {
        return (
            <Popconfirm
                title={`Permanently delete key "${personalAPIKey.label}"?`}
                okText="Delete Key"
                okType="danger"
                icon={<ExclamationCircleOutlined style={{ color: red.primary }} />}
                placement="left"
                onConfirm={() => {
                    deleteKey(personalAPIKey)
                }}
            >
                <a className="text-danger">Delete</a>
            </Popconfirm>
        )
    }

    const columns = [
        {
            title: 'Label',
            dataIndex: 'label',
            key: 'label',
        },
        {
            title: 'Value',
            dataIndex: 'value',
            key: 'value',
        },
        {
            title: 'Last Used',
            dataIndex: 'last_used_at',
            key: 'last_used_at',
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            key: 'created_at',
        },
        {
            title: '',
            dataIndex: 'actions',
            key: 'actions',
            align: 'center',
            render: RowActions,
        },
    ]

    const processedKeysData = keys.map((key) => {
        return {
            ...key,
            value: key.value ? <b>{key.value}</b> : <i>secret</i>,
            last_used_at: key.last_used_at ? humanFriendlyDetailedTime(key.last_used_at) : 'never',
            created_at: humanFriendlyDetailedTime(key.created_at),
        }
    })

    return (
        <Table
            dataSource={processedKeysData}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
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
                <a href="https://posthog.com/docs/api/api#authentication">
                    More about API authentication in PostHog docs.
                </a>
            </p>
            <Button
                type="primary"
                onClick={() => {
                    setIsCreateKeyModalVisible(true)
                }}
            >
                + Create a Personal API Key
            </Button>
            <CreateKeyModal isVisible={isCreateKeyModalVisible} setIsVisible={setIsCreateKeyModalVisible} />
            <PersonalAPIKeysTable />
        </>
    )
}
