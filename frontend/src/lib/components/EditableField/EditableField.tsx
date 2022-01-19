import React, { useEffect, useState } from 'react'
import './EditableField.scss'
import { IconClose, IconEdit, IconSave } from '../icons'
import { LemonButton } from '../LemonButton'
import AutosizeInput from 'react-input-autosize'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'

interface EditableFieldPropsBase {
    /** What this field stands for. */
    name: string
    value: string
    onChange?: (value: string) => void
    placeholder?: string
    minLength?: number
    multiline?: boolean
    compactButtons?: boolean
    className?: string
    'data-attr'?: string
}

type EditableFieldProps =
    | (EditableFieldPropsBase & {
          onSave: (value: string) => void
          controlledMode?: undefined
      })
    | (EditableFieldPropsBase & {
          onSave?: undefined
          controlledMode: 'edit' | 'view'
      })

export function EditableField({
    name,
    value,
    onChange,
    onSave,
    controlledMode,
    placeholder,
    minLength,
    multiline = false,
    compactButtons = false,
    className,
    'data-attr': dataAttr,
}: EditableFieldProps): JSX.Element {
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [tentativeValue, setTentativeValue] = useState(value)

    useEffect(() => {
        setTentativeValue(value)
    }, [value])

    const isEditing = !controlledMode ? localIsEditing : controlledMode === 'edit'
    const isSaveable = !minLength || tentativeValue.length >= minLength

    const cancel = (): void => {
        setLocalIsEditing(false)
        setTentativeValue(value)
    }

    const save = (): void => {
        onSave?.(tentativeValue)
        setLocalIsEditing(false)
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
                    {!controlledMode ? (
                        <>
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
                    ) : null}
                </>
            ) : (
                <>
                    {value || <i>{placeholder}</i>}
                    {!controlledMode ? (
                        <LemonButton
                            title="Edit"
                            icon={<IconEdit />}
                            compact={compactButtons}
                            onClick={() => setLocalIsEditing(true)}
                        />
                    ) : null}
                </>
            )}
        </div>
    )
}
