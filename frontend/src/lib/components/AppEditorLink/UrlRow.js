import React, { useState } from 'react'

import { appEditorUrl, defaultUrl } from './utils'

export function UrlRow ({ actionId, url, saveUrl, deleteUrl }) {
    const [isEditing, setIsEditing] = useState(url === defaultUrl)
    const [savedValue, setSavedValue] = useState(url || defaultUrl)
    const [editedValue, setEditedValue] = useState(url || defaultUrl)

    return (
        <li className="list-group-item">
            {isEditing ? (
                <div key='form' style={{ display: 'flex', width: '100%' }}>
                    <input
                        value={editedValue}
                        onChange={(e) => setEditedValue(e.target.value)}
                        autoFocus
                        style={{ flex: '1' }}
                        type="url"
                        className='form-control'
                        placeholder={defaultUrl}
                    />
                    <button className='btn btn-primary' style={{ marginLeft: 5 }} onClick={() => {
                        if (editedValue === defaultUrl) {
                            deleteUrl()
                        } else {
                            saveUrl(editedValue, () => {
                                setIsEditing(false);
                                setSavedValue(editedValue)
                            })
                        }
                    }}>Save</button>
                    <button className='btn btn-outline-secondary' style={{ marginLeft: 5 }} onClick={() => {
                        if (url === defaultUrl) {
                            deleteUrl()
                        } else {
                            setIsEditing(false)
                            setEditedValue(savedValue || url || defaultUrl)
                        }
                    }}>Cancel</button>
                </div>
            ) : typeof url === 'undefined' ? (
                <div key='add-new'>
                    <a href='#' onClick={e => {e.preventDefault(); setIsEditing(true)}}>+ Add Another URL</a>
                </div>
            ) : (
                <div key='list'>
                    <div style={{ float: 'right' }}>
                        <button className='no-style' onClick={() => setIsEditing(true)}>
                            <i className='fi flaticon-edit text-primary' />
                        </button>
                        <button className='no-style text-danger' onClick={deleteUrl}>
                            <i className='fi flaticon-basket' />
                        </button>
                    </div>
                    <a href={appEditorUrl(actionId, editedValue)}>{editedValue}</a>
                </div>
            )}
        </li>
    )
}
