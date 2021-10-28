import { Button, Input } from 'antd'
import { AvailableFeature } from '~/types'
import { EditOutlined } from '@ant-design/icons'
import React, { useEffect, useState } from 'react'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import './EditableField.scss'

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
    const flagEnabled = useValues(featureFlagLogic).featureFlags[FEATURE_FLAGS.SAVED_INSIGHTS]
    const featureEnabled = useValues(userLogic).user?.organization?.available_features?.includes(
        AvailableFeature.DASHBOARD_COLLABORATION
    )
    const isEditable = flagEnabled && featureEnabled
    const [isEditing, setIsEditing] = useState(false)
    const [editedValue, setEditedValue] = useState(value)
    useEffect(() => {
        setEditedValue(value)
    }, [value])
    return (
        <div className={`editable-field${className ? ` ${className}` : ''}`} data-attr={dataAttr}>
            {isEditable && isEditing ? (
                <div className="ant-input-affix-wrapper ant-input-affix-wrapper-lg editable-textarea-wrapper">
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
                <div className={'view-mode'}>
                    <span className="field">{value || placeholder}</span>
                    {isEditable && (
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
