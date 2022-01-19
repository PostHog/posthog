import React, { useEffect, useState } from 'react'
import './EditableField.scss'
import { IconClose, IconEdit, IconSave } from '../icons'
import { LemonButton } from '../LemonButton'
import AutosizeInput from 'react-input-autosize'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'

interface EditableFieldProps {
    /** What this field stands for. */
    name: string
    value: string
    onChange?: (value: string) => void
    onSave: (value: string) => void
    placeholder?: string
    minLength?: number
    multiline?: boolean
    compactButtons?: boolean
    className?: string
    'data-attr'?: string
}

export function EditableField({
    name,
    value,
    onChange,
    onSave,
    placeholder,
    minLength,
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

    const isSaveable = !minLength || tentativeValue.length >= minLength

    const cancel = (): void => {
        setIsEditing(false)
        setTentativeValue(value)
    }

    const save = (): void => {
        onSave?.(tentativeValue)
        setIsEditing(false)
    }

    return (
        <div className={clsx('EditableField', multiline && 'EditableField--multiline', className)} data-attr={dataAttr}>
            {isEditing ? (
                <>
                    {multiline ? (
                        <TextareaAutosize
                            name={name}
                            value={tentativeValue}
                            onChange={(e) => {
                                onChange?.(e.target.value)
                                setTentativeValue(e.target.value)
                            }}
                            onKeyDown={(e) => {
                                if (isSaveable && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                                    save() // Save on Cmd/Ctrl + Enter press (Cmd/Ctrl required because of newlines)
                                }
                            }}
                            placeholder={placeholder}
                            minLength={minLength}
                            autoFocus
                        />
                    ) : (
                        <AutosizeInput
                            name={name}
                            value={tentativeValue}
                            onChange={(e) => {
                                onChange?.(e.target.value)
                                setTentativeValue(e.target.value)
                            }}
                            onKeyDown={(e) => {
                                if (isSaveable && e.key === 'Enter') {
                                    save() // Save on Enter press
                                }
                            }}
                            placeholder={placeholder}
                            minLength={minLength}
                            autoFocus
                            injectStyles={false}
                        />
                    )}
                    <LemonButton
                        title="Cancel editing"
                        icon={<IconClose />}
                        status="danger"
                        compact={compactButtons}
                        onClick={cancel}
                    />
                    <LemonButton
                        title={
                            !minLength
                                ? 'Save'
                                : `Save (at least ${pluralize(minLength, 'character', 'characters')} required)`
                        }
                        icon={<IconSave />}
                        compact={compactButtons}
                        disabled={!isSaveable}
                        onClick={save}
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
