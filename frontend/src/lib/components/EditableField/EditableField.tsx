import './EditableField.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useEffect, useRef, useState } from 'react'
import TextareaAutosize from 'react-textarea-autosize'

import { IconPencil } from '@posthog/icons'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { RawInputAutosize } from 'lib/lemon-ui/LemonInput/RawInputAutosize'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconMarkdown } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'

export interface EditableFieldProps {
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
    /** Whether to render the content as Markdown in view mode. */
    markdown?: boolean
    compactButtons?: boolean | 'xsmall' // The 'xsmall' is somewhat hacky, but necessary for 3000 breadcrumbs
    /** Whether this field should be gated behind a "paywall". */
    paywallFeature?: AvailableFeature
    /** Controlled mode. */
    mode?: 'view' | 'edit'
    onModeToggle?: (newMode: 'view' | 'edit') => void
    /** @default 'outlined' */
    editingIndication?: 'outlined' | 'underlined'
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
    autoFocus = false,
    multiline = false,
    markdown = false,
    compactButtons = false,
    paywallFeature,
    mode,
    onModeToggle,
    editingIndication = 'outlined',
    className,
    style,
    'data-attr': dataAttr,
    saveButtonText = 'Save',
    notice,
}: EditableFieldProps): JSX.Element {
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [localIsEditing, setLocalIsEditing] = useState(mode === 'edit')
    const [localTentativeValue, setLocalTentativeValue] = useState(value)
    const [isDisplayTooltipNeeded, setIsDisplayTooltipNeeded] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)
    const displayRef = useRef<HTMLSpanElement>(null)
    const previousIsEditing = useRef<boolean>()

    useEffect(() => {
        setLocalTentativeValue(value)
    }, [value])

    useEffect(() => {
        setLocalIsEditing(mode === 'edit')
    }, [mode])

    useEffect(() => {
        // We always want to focus when switching to edit mode, but can't use autoFocus, because we don't want this to
        // happen when the component is _initially_ rendered in edit mode. The `previousIsEditing.current === false`
        // check is important for this, because only `false` means that the component was previously rendered in view
        // mode. `undefined` means that the component was never rendered before.
        if (inputRef.current && previousIsEditing.current === false && localIsEditing) {
            const endOfInput = inputRef.current.value.length
            inputRef.current.setSelectionRange(endOfInput, endOfInput)
            inputRef.current.focus()
        }
        previousIsEditing.current = localIsEditing
    }, [localIsEditing])

    useResizeObserver({
        ref: containerRef,
        onResize: () => {
            if (displayRef.current) {
                setIsDisplayTooltipNeeded(displayRef.current.scrollWidth > displayRef.current.clientWidth)
            }
        },
    })
    const isSaveable = !minLength || localTentativeValue.length >= minLength

    const mouseDownOnCancelButton = (e: React.MouseEvent): void => {
        // if saveOnBlur is set the onBlur handler of the input fires before the onClick event of the button
        // this onMouseDown handler fires before the input can see the click and fire onBlur
        e.preventDefault()
    }

    const cancel = (): void => {
        setLocalIsEditing(false)
        setLocalTentativeValue(value)
        onModeToggle?.('view')
    }

    const save = (): void => {
        onSave?.(localTentativeValue)
        setLocalIsEditing(false)
        onModeToggle?.('view')
    }

    const isEditing = mode === 'edit' || localIsEditing

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

    const handleDoubleClick = (): void => {
        if (!isEditing) {
            guardAvailableFeature(paywallFeature, () => {
                setLocalIsEditing(true)
                onModeToggle?.('edit')
            })
        }
    }

    return (
        <div
            className={clsx(
                'EditableField',
                multiline && 'EditableField--multiline',
                isEditing && 'EditableField--editing',
                editingIndication === 'underlined' && 'EditableField--underlined',
                className
            )}
            data-attr={dataAttr}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            ref={containerRef}
            onDoubleClick={handleDoubleClick}
        >
            <div className="EditableField__highlight">
                {isEditing ? (
                    <>
                        {multiline ? (
                            <TextareaAutosize
                                name={name}
                                value={localTentativeValue}
                                onChange={(e) => {
                                    onChange?.(e.target.value)
                                    setLocalTentativeValue(e.target.value)
                                }}
                                onBlur={saveOnBlur ? (localTentativeValue !== value ? save : cancel) : undefined}
                                onKeyDown={handleKeyDown}
                                placeholder={placeholder}
                                minLength={minLength}
                                maxLength={maxLength}
                                autoFocus={autoFocus}
                                ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                            />
                        ) : (
                            <RawInputAutosize
                                name={name}
                                value={localTentativeValue}
                                onChange={(e) => {
                                    guardAvailableFeature(paywallFeature, () => {
                                        onChange?.(e.currentTarget.value)
                                        setLocalTentativeValue(e.currentTarget.value)
                                    })
                                }}
                                onBlur={saveOnBlur ? (localTentativeValue !== value ? save : cancel) : undefined}
                                onKeyDown={handleKeyDown}
                                placeholder={placeholder}
                                minLength={minLength}
                                maxLength={maxLength}
                                autoFocus={autoFocus}
                                ref={inputRef as React.RefObject<HTMLInputElement>}
                                wrapperClassName="self-center py-px"
                            />
                        )}
                        {(!mode || !!onModeToggle) && !saveOnBlur && (
                            <div className="EditableField__actions">
                                {markdown && (
                                    <Tooltip title="Markdown formatting support">
                                        <span className="flex items-center">
                                            <IconMarkdown className="text-secondary text-2xl" />
                                        </span>
                                    </Tooltip>
                                )}
                                <LemonButton
                                    title="Cancel editing"
                                    size={typeof compactButtons === 'string' ? compactButtons : 'small'}
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
                                    size={typeof compactButtons === 'string' ? compactButtons : 'small'}
                                    disabled={!isSaveable}
                                    onClick={save}
                                    type="primary"
                                >
                                    {saveButtonText}
                                </LemonButton>
                            </div>
                        )}
                    </>
                ) : (
                    <>
                        {localTentativeValue && markdown ? (
                            <LemonMarkdown lowKeyHeadings>{localTentativeValue}</LemonMarkdown>
                        ) : (
                            <Tooltip
                                title={isDisplayTooltipNeeded ? localTentativeValue : undefined}
                                placement="bottom-start"
                                delayMs={0}
                            >
                                <span className="EditableField__display" ref={displayRef}>
                                    {localTentativeValue || <i>{placeholder}</i>}
                                </span>
                            </Tooltip>
                        )}
                        {(!mode || !!onModeToggle) && (
                            <div className="EditableField__actions">
                                <LemonButton
                                    title="Edit"
                                    icon={<IconPencil />}
                                    size={compactButtons ? 'small' : undefined}
                                    onClick={() => {
                                        guardAvailableFeature(paywallFeature, () => {
                                            setLocalIsEditing(true)
                                            onModeToggle?.('edit')
                                        })
                                    }}
                                    data-attr={`edit-prop-${name}`}
                                    noPadding
                                />
                            </div>
                        )}
                    </>
                )}
            </div>
            {!isEditing && notice && (
                <Tooltip title={notice.tooltip} placement="right">
                    <span className="flex items-center">
                        {React.cloneElement(notice.icon, {
                            ...notice.icon.props,
                            className: clsx(notice.icon.props.className, 'EditableField__notice'),
                        })}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
