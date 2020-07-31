import React, { useState, useRef } from 'react'
import { Table, Modal, Button, Input } from 'antd'
import { useActions } from 'kea'
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

function CreateKeyModal({ visible, setVisible }) {
    const { createPersonalAPIKeyRequest } = useActions(userLogic)

    const inputRef = useRef()

    return (
        <Modal
            title="Creating a Personal API Key"
            okText="Create Key"
            cancelText="Cancel"
            onOk={() => {
                createPersonalAPIKeyRequest(inputRef.current.state.value.trim())
                setVisible(false)
                inputRef.current.state.value = ''
            }}
            onCancel={() => {
                setVisible(false)
                inputRef.current.state.value = ''
            }}
            visible={visible}
        >
            <Input
                addonBefore="Label"
                ref={inputRef}
                placeholder='for example "Zapier integration"'
                minLength={0}
                maxLength={40}
            />
            <p style={{ marginTop: '1rem', marginBottom: 0 }}>
                Key value <b>will only ever be shown once</b>, immediately after creation.
                <br />
                Copy it to your destination right away.
            </p>
        </Modal>
    )
}

function PersonalAPIKeysTable({ keys }) {
    const { confirm } = Modal
    const { deletePersonalAPIKeyRequest } = useActions(userLogic)

    function RowActions(_text, personalAPIKey) {
        const handleClick = () => {
            confirm({
                title: `Delete personal API key "${personalAPIKey.label}"?`,
                icon: <ExclamationCircleOutlined />,
                content: 'It will be permanently invalidated.',
                okText: 'Delete Key',
                okType: 'danger',
                cancelText: 'Cancel',
                onOk() {
                    deletePersonalAPIKeyRequest(personalAPIKey)
                },
            })
        }

        return (
            <div>
                <a className="text-danger" onClick={handleClick}>
                    <DeleteOutlined />
                </a>
            </div>
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
            title: 'Last Used At',
            dataIndex: 'last_used_at',
            key: 'last_used_at',
        },
        {
            title: 'Created At',
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
            last_used_at: key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'never',
            created_at: new Date(key.created_at).toLocaleString(),
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

export function PersonalAPIKeys({ user }) {
    const [isCreateKeyModalOpen, setIsCreateKeyModalOpen] = useState(false)

    return (
        <>
            <p>
                These keys allow full access to your personal account through the API, as if you were logged in. You can
                also use them in integrations, such as <a href="https://zapier.com/apps/posthog/">our Zapier one</a>.
                <br />
                If you have any suspicion that one of these may be compromised, delete it and use a new one.
            </p>
            <Button
                type="primary"
                onClick={() => {
                    setIsCreateKeyModalOpen(true)
                }}
            >
                + Create a Personal API Key
            </Button>
            <CreateKeyModal visible={isCreateKeyModalOpen} setVisible={setIsCreateKeyModalOpen} />
            <PersonalAPIKeysTable keys={user.personal_api_keys} />
        </>
    )
}
