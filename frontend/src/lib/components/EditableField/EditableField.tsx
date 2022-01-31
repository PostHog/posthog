import React, { useEffect, useState } from 'react'
import './EditableField.scss'
import { IconEdit } from '../icons'
import { LemonButton } from '../LemonButton'
import AutosizeInput from 'react-input-autosize'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'
import { Tooltip } from '../Tooltip'
import { useValues } from 'kea'
import { AvailableFeature } from '~/types'
import { userLogic } from 'scenes/userLogic'

interface EditableFieldProps {
    /** What this field stands for. */
    name: string
    value: string
    onChange?: (value: string) => void
    onSave: (value: string) => void
    placeholder?: string
    minLength?: number
    maxLength?: number
    multiline?: boolean
    compactButtons?: boolean
    /** Whether this field should be gated based on AvailableFeature.DASHBOARD_COLLABORATION. */
    paywall?: boolean
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
    maxLength,
    multiline = false,
    compactButtons = false,
    paywall = false,
    className,
    'data-attr': dataAttr,
}: EditableFieldProps): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)

    const [isEditing, setIsEditing] = useState(false)
    const [tentativeValue, setTentativeValue] = useState(value)

    useEffect(() => {
        setTentativeValue(value)
    }, [value])

    const isGated = paywall && !hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION)
    const isSaveable = !minLength || tentativeValue.length >= minLength

    const cancel = (): void => {
        setIsEditing(false)
        setTentativeValue(value)
    }

    const save = (): void => {
        onSave?.(tentativeValue)
        setIsEditing(false)
    }

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
        >
            <Tooltip
                placement="right"
                title={
                    isGated
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
                                    onKeyDown={handleKeyDown}
                                    placeholder={placeholder}
                                    minLength={minLength}
                                    maxLength={maxLength}
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
                                    onKeyDown={handleKeyDown}
                                    placeholder={placeholder}
                                    minLength={minLength}
                                    maxLength={maxLength}
                                    autoFocus
                                    className="EditableField__autosize"
                                    injectStyles={false}
                                />
                            )}
                            <LemonButton title="Cancel editing" compact onClick={cancel} type="secondary">
                                Cancel
                            </LemonButton>
                            <LemonButton
                                title={
                                    !minLength
                                        ? 'Save'
                                        : `Save (at least ${pluralize(minLength, 'character', 'characters')} required)`
                                }
                                compact
                                disabled={!isSaveable}
                                onClick={save}
                                type="primary"
                            >
                                Save
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            {tentativeValue || <i>{placeholder}</i>}
                            <LemonButton
                                title="Edit"
                                icon={<IconEdit />}
                                compact={compactButtons}
                                onClick={() => setIsEditing(true)}
                                data-attr={`edit-prop-${name}`}
                                disabled={isGated}
                            />
                        </>
                    )}
                </div>
            </Tooltip>
        </div>
    )
}
