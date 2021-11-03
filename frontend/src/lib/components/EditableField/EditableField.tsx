import { Button, Input } from 'antd'
import { EditOutlined } from '@ant-design/icons'
import React, { useEffect, useState } from 'react'
import { useValues } from 'kea'
import './EditableField.scss'
import { insightLogic } from 'scenes/insights/insightLogic'

interface EditableFieldProps {
    name: string
    value: string
    placeholder: string
    className: string
    dataAttr: string
    onChange: (value: string) => void
    multiline?: boolean
}

export function EditableField({
    name,
    value,
    onChange,
    className,
    dataAttr,
    placeholder,
    multiline,
}: EditableFieldProps): JSX.Element {
    const { metadataEditable } = useValues(insightLogic)
    const [isEditing, setIsEditing] = useState(false)
    const [editedValue, setEditedValue] = useState(value)
    useEffect(() => {
        setEditedValue(value)
    }, [value])
    return (
        <div
            className={`editable-field${className ? ` ${className}` : ''} ${isEditing ? 'edit-mode' : 'view-mode'}`}
            data-attr={dataAttr}
        >
            {metadataEditable && isEditing ? (
                <div className="edit-container ant-input-affix-wrapper ant-input-affix-wrapper-lg editable-textarea-wrapper">
                    <Input.TextArea
                        autoFocus
                        placeholder={placeholder}
                        value={multiline ? editedValue : editedValue.split('\n').join('')}
                        onChange={(e) => setEditedValue(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                                onChange(editedValue)
                                setIsEditing(false)
                            }
                        }}
                        autoSize={{ minRows: 1, maxRows: 5 }}
                    />

                    <Button className="btn-cancel" size="small" onClick={() => setIsEditing(false)}>
                        Cancel
                    </Button>
                    <Button
                        className="ml-025"
                        type="primary"
                        size="small"
                        onClick={() => {
                            onChange(editedValue)
                            setIsEditing(false)
                        }}
                    >
                        Done
                    </Button>
                </div>
            ) : (
                <div className="view-container">
                    <span className="field">{value || placeholder}</span>
                    {metadataEditable && (
                        <Button
                            type="link"
                            onClick={() => {
                                setEditedValue(value)
                                setIsEditing(true)
                            }}
                            className="btn-edit"
                            data-attr={`edit-prop-${name}`}
                            title={`Edit ${name}`}
                        >
                            <EditOutlined />
                        </Button>
                    )}
                </div>
            )}
        </div>
    )
}
