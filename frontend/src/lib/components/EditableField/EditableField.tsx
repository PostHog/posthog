import React, { useEffect, useState } from 'react'
import './EditableField.scss'
import { IconClose, IconEdit, IconSave } from '../icons'
import { LemonButton } from '../LemonButton'
import AutosizeInput from 'react-input-autosize'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'

interface EditableFieldProps {
    /** What this field stands for. */
    name: string
    /** Current value. */
    value: string
    /** Value change callback. */
    onChange: (value: string) => void
    placeholder?: string
    multiline?: boolean
    compactButtons?: boolean
    className?: string
    'data-attr'?: string
}

export function EditableField({
    name,
    value,
    onChange,
    placeholder,
    multiline = false,
    compactButtons = false,
    className,
    'data-attr': dataAttr,
}: EditableFieldProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [tentativeValue, setTentativeValue] = useState(value)

    useEffect(() => {
        setTentativeValue(value)
    }, [value])

    return (
        <div className={clsx('EditableField', multiline && 'EditableField--multiline', className)} data-attr={dataAttr}>
            {isEditing ? (
                <>
                    {multiline ? (
                        <TextareaAutosize
                            name={name}
                            value={tentativeValue}
                            onChange={(e) => setTentativeValue(e.target.value)}
                            placeholder={placeholder}
                            autoFocus
                        />
                    ) : (
                        <AutosizeInput
                            name={name}
                            value={tentativeValue}
                            onChange={(e) => setTentativeValue(e.target.value)}
                            placeholder={placeholder}
                            autoFocus
                            injectStyles={false}
                        />
                    )}
                    <LemonButton
                        title="Cancel editing"
                        icon={<IconClose />}
                        status="danger"
                        compact={compactButtons}
                        onClick={() => {
                            setIsEditing(false)
                            setTentativeValue(value)
                        }}
                    />
                    <LemonButton
                        title="Save"
                        icon={<IconSave />}
                        compact={compactButtons}
                        onClick={() => {
                            onChange(tentativeValue)
                            setIsEditing(false)
                        }}
                    />
                </>
            ) : (
                <>
                    {value || <i>{placeholder}</i>}
                    <LemonButton
                        title="Edit"
                        icon={<IconEdit />}
                        compact={compactButtons}
                        onClick={() => setIsEditing(true)}
                    />
                </>
            )}
        </div>
    )
}
