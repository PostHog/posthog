import React, { useState } from 'react'

import { appEditorUrl, defaultUrl } from './utils'
import { Input, Button, List } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'

interface UrlRowInterface {
    actionId?: number
    url: string
    saveUrl: (url: string) => void
    deleteUrl: () => void
    allowNavigation?: boolean
}

export function UrlRow({ actionId, url, saveUrl, deleteUrl, allowNavigation }: UrlRowInterface): JSX.Element {
    const [isEditing, setIsEditing] = useState(url === defaultUrl)
    const [savedValue, setSavedValue] = useState(url || defaultUrl)
    const [editedValue, setEditedValue] = useState(url || defaultUrl)

    return (
        <List.Item>
            {isEditing ? (
                <form
                    key="form"
                    style={{ display: 'flex', width: '100%' }}
                    onSubmit={(e) => {
                        e.preventDefault()
                        if (editedValue === defaultUrl) {
                            deleteUrl()
                        } else {
                            // Validate that the wildcard is valid and we're not trying to match subdomains
                            // See https://regex101.com/r/UMBc9g/1 for tests
                            if (editedValue.indexOf('*') > -1 && !editedValue.match(/^(.*)\*[^\*]*\.[^\*]+\.[^\*]+$/)) {
                                alert(
                                    'You can only wildcard subdomains. If you wildcard the domain or TLD, people might be able to gain access to your PostHog data.'
                                )
                                return
                            }
                            saveUrl(editedValue)
                            setIsEditing(false)
                            setSavedValue(editedValue)
                        }
                    }}
                >
                    <Input
                        value={editedValue}
                        onChange={(e) => setEditedValue(e.target.value)}
                        autoFocus
                        required
                        style={{ flex: '1' }}
                        type="url"
                        placeholder={defaultUrl}
                    />
                    <Button style={{ marginLeft: 5 }} htmlType="submit" type="primary">
                        Save
                    </Button>
                    <Button
                        htmlType="button"
                        style={{ marginLeft: 5 }}
                        onClick={() => {
                            if (url === defaultUrl) {
                                deleteUrl()
                            } else {
                                setIsEditing(false)
                                setEditedValue(savedValue || url || defaultUrl)
                            }
                        }}
                    >
                        Cancel
                    </Button>
                </form>
            ) : typeof url === 'undefined' ? (
                <div key="add-new">
                    <a
                        href="#"
                        onClick={(e) => {
                            e.preventDefault()
                            setIsEditing(true)
                        }}
                    >
                        + Add Another URL
                    </a>
                </div>
            ) : (
                <div key="list" style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                    <a
                        data-attr="app-url-item"
                        href={appEditorUrl(editedValue, actionId)}
                        target="_blank"
                        rel="noopener"
                        onClick={(e) => !allowNavigation && e.preventDefault()}
                    >
                        {editedValue}
                    </a>
                    <span style={{ float: 'right' }}>
                        <EditOutlined
                            onClick={() => setIsEditing(true)}
                            style={{ color: 'var(--primary)', marginLeft: 8 }}
                        />
                        <DeleteOutlined onClick={deleteUrl} style={{ color: 'var(--danger)', marginLeft: 8 }} />
                    </span>
                </div>
            )}
        </List.Item>
    )
}
