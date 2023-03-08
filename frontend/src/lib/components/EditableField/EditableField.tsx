import React, { useEffect, useState } from 'react'
import './EditableField.scss'
import { IconEdit } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import AutosizeInput from 'react-input-autosize'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

interface EditableFieldProps {
    /** What this field stands for. */
    name: string
    value: string
    onChange?: (value: string) => void
    onSave?: (value: string) => void
    saveOnBlur?: boolean
    placeholder?: string
    minLength?: number
    maxLength?: number
    autoFocus?: boolean
    multiline?: boolean
    compactButtons?: boolean
    /** Whether this field should be gated behind a "paywall". */
    paywall?: boolean
    /** Controlled mode. */
    mode?: 'view' | 'edit'
    className?: string
    style?: React.CSSProperties
    'data-attr'?: string
    saveButtonText?: string
    /** Extra information shown next to the field. */
    notice?: {
        icon: React.ReactElement
        tooltip: string
    }
}

export function EditableField({
    name,
    value,
    onChange,
    onSave,
    saveOnBlur = false,
    placeholder,
    minLength,
    maxLength,
    autoFocus = true,
    multiline = false,
    compactButtons = false,
    paywall = false,
    mode,
    className,
    style,
    'data-attr': dataAttr,
    saveButtonText = 'Save',
    notice,
}: EditableFieldProps): JSX.Element {
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [tentativeValue, setTentativeValue] = useState(value)

    useEffect(() => {
        setTentativeValue(value)
    }, [value])

    const isSaveable = !minLength || tentativeValue.length >= minLength

    const mouseDownOnCancelButton = (e: React.MouseEvent): void => {
        // if saveOnBlur is set the onBlur handler of the input fires before the onClick event of the button
        // this onMouseDown handler fires before the input can see the click and fire onBlur
        e.preventDefault()
    }

    const cancel = (): void => {
        setLocalIsEditing(false)
        setTentativeValue(value)
    }

    const save = (): void => {
        onSave?.(tentativeValue)
        setLocalIsEditing(false)
    }

    const isEditing = !paywall && (mode === 'edit' || localIsEditing)

    const handleKeyDown = (e: React.KeyboardEvent<HTMLElement>): void => {
        if (isEditing) {
            // Cmd/Ctrl are required in addition to Enter if newlines are permitted
            if (isSaveable && e.key === 'Enter' && (!multiline || e.metaKey || e.ctrlKey)) {
                save() // Save on Enter press
                e.stopPropagation()
                e.preventDefault()
            } else if (e.key === 'Escape') {
                cancel()
                e.stopPropagation()
                e.preventDefault()
            }
        }
    }

    return (
        <div
            className={clsx(
                'EditableField',
                multiline && 'EditableField--multiline',
                isEditing && 'EditableField--editing',
                className
            )}
            data-attr={dataAttr}
            style={style}
        >
            <Tooltip
                placement="right"
                title={
                    paywall
                        ? "This field is part of PostHog's collaboration feature set and requires a premium plan."
                        : undefined
                }
            >
                <div className="EditableField--highlight">
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
                                    onBlur={saveOnBlur ? (tentativeValue !== value ? save : cancel) : undefined}
                                    onKeyDown={handleKeyDown}
                                    placeholder={placeholder}
                                    minLength={minLength}
                                    maxLength={maxLength}
                                    autoFocus={autoFocus}
                                />
                            ) : (
                                <AutosizeInput
                                    name={name}
                                    value={tentativeValue}
                                    onChange={(e) => {
                                        onChange?.(e.target.value)
                                        setTentativeValue(e.target.value)
                                    }}
                                    onBlur={saveOnBlur ? (tentativeValue !== value ? save : cancel) : undefined}
                                    onKeyDown={handleKeyDown}
                                    placeholder={placeholder}
                                    minLength={minLength}
                                    maxLength={maxLength}
                                    autoFocus={autoFocus}
                                    className="EditableField__autosize"
                                    injectStyles={false}
                                />
                            )}
                            {!mode && (
                                <>
                                    <LemonButton
                                        title="Cancel editing"
                                        size="small"
                                        onClick={cancel}
                                        type="secondary"
                                        onMouseDown={mouseDownOnCancelButton}
                                    >
                                        Cancel
                                    </LemonButton>
                                    <LemonButton
                                        title={
                                            !minLength
                                                ? 'Save'
                                                : `Save (at least ${pluralize(
                                                      minLength,
                                                      'character',
                                                      'characters'
                                                  )} required)`
                                        }
                                        size="small"
                                        disabled={!isSaveable}
                                        onClick={save}
                                        type="primary"
                                    >
                                        {saveButtonText}
                                    </LemonButton>
                                </>
                            )}
                        </>
                    ) : (
                        <>
                            {tentativeValue || <i>{placeholder}</i>}
                            {!mode && (
                                <LemonButton
                                    title="Edit"
                                    icon={<IconEdit />}
                                    size={compactButtons ? 'small' : undefined}
                                    onClick={() => setLocalIsEditing(true)}
                                    data-attr={`edit-prop-${name}`}
                                    disabled={paywall}
                                />
                            )}
                        </>
                    )}
                </div>
            </Tooltip>
            {!isEditing && notice && (
                <Tooltip title={notice.tooltip} placement="right">
                    {React.cloneElement(notice.icon, {
                        ...notice.icon.props,
                        className: clsx(notice.icon.props.className, 'EditableField__notice'),
                    })}
                </Tooltip>
            )}
        </div>
    )
}
