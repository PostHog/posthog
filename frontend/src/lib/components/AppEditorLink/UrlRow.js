import React, { useState } from 'react'

import { appEditorUrl, defaultUrl } from './utils'
import { Input, Button, List } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'

export function UrlRow({ actionId, url, saveUrl, deleteUrl, allowNavigation }) {
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
                        type="secondary"
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
                        href={appEditorUrl(actionId, editedValue)}
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
