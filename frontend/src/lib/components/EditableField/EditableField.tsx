import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import './EditableField.scss'
import { IconEdit, IconMarkdown } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import TextareaAutosize from 'react-textarea-autosize'
import clsx from 'clsx'
import { pluralize } from 'lib/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

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
    paywall?: boolean
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
    autoFocus = true,
    multiline = false,
    markdown = false,
    compactButtons = false,
    paywall = false,
    mode,
    onModeToggle,
    editingIndication = 'outlined',
    className,
    style,
    'data-attr': dataAttr,
    saveButtonText = 'Save',
    notice,
}: EditableFieldProps): JSX.Element {
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [localTentativeValue, setLocalTentativeValue] = useState(value)

    useEffect(() => {
        setLocalTentativeValue(value)
    }, [value])
    useEffect(() => {
        setLocalIsEditing(mode === 'edit')
    }, [mode])

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
                editingIndication === 'underlined' && 'EditableField--underlined',
                className
            )}
            data-attr={dataAttr}
            // eslint-disable-next-line react/forbid-dom-props
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
                                />
                            ) : (
                                <AutosizeInput
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
                                />
                            )}
                            {(!mode || !!onModeToggle) && (
                                <div className="EditableField__actions">
                                    {markdown && (
                                        <Tooltip title="Markdown formatting support">
                                            <IconMarkdown className="text-muted text-2xl" />
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
                                localTentativeValue || <i>{placeholder}</i>
                            )}
                            {(!mode || !!onModeToggle) && (
                                <div className="EditableField__actions">
                                    <LemonButton
                                        title="Edit"
                                        icon={<IconEdit />}
                                        size={
                                            typeof compactButtons === 'string'
                                                ? compactButtons
                                                : compactButtons
                                                ? 'small'
                                                : undefined
                                        }
                                        onClick={() => {
                                            setLocalIsEditing(true)
                                            onModeToggle?.('edit')
                                        }}
                                        data-attr={`edit-prop-${name}`}
                                        disabled={paywall}
                                        noPadding
                                    />
                                </div>
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

const AutosizeInput = ({
    name,
    value,
    onChange,
    placeholder,
    onBlur,
    onKeyDown,
    minLength,
    maxLength,
    autoFocus,
}: {
    name: string
    value: string
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
    onBlur: (() => void) | undefined
    placeholder?: string
    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => void
    minLength?: number
    maxLength?: number
    autoFocus?: boolean
}): JSX.Element => {
    const [inputWidth, setInputWidth] = useState<number | string>(1)
    const inputRef = useRef<HTMLInputElement>(null)
    const sizerRef = useRef<HTMLDivElement>(null)
    const placeHolderSizerRef = useRef<HTMLDivElement>(null)

    const copyStyles = (styles: CSSStyleDeclaration, node: HTMLDivElement): void => {
        node.style.fontSize = styles.fontSize
        node.style.fontFamily = styles.fontFamily
        node.style.fontWeight = styles.fontWeight
        node.style.fontStyle = styles.fontStyle
        node.style.letterSpacing = styles.letterSpacing
        node.style.textTransform = styles.textTransform
    }

    const inputStyles = useMemo(() => {
        return inputRef.current ? window.getComputedStyle(inputRef.current) : null
    }, [inputRef.current])

    useLayoutEffect(() => {
        if (inputStyles && placeHolderSizerRef.current) {
            copyStyles(inputStyles, placeHolderSizerRef.current)
        }
    }, [placeHolderSizerRef, placeHolderSizerRef])

    useLayoutEffect(() => {
        if (inputStyles && sizerRef.current) {
            copyStyles(inputStyles, sizerRef.current)
        }
    }, [inputStyles, sizerRef])

    useLayoutEffect(() => {
        if (!sizerRef.current || !placeHolderSizerRef.current) {
            return
        }
        let newInputWidth
        if (placeholder && !value) {
            newInputWidth = Math.max(sizerRef.current.scrollWidth, placeHolderSizerRef.current.scrollWidth) + 2
        } else {
            newInputWidth = sizerRef.current.scrollWidth + 2
        }
        if (newInputWidth !== inputWidth) {
            setInputWidth(newInputWidth)
        }
    }, [sizerRef.current, placeHolderSizerRef.current, placeholder, value])

    return (
        <div className="EditableField__autosize">
            <input
                name={name}
                value={value}
                placeholder={placeholder}
                onChange={onChange}
                onKeyDown={onKeyDown}
                onBlur={onBlur}
                minLength={minLength}
                maxLength={maxLength}
                autoFocus={autoFocus}
                ref={inputRef}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={{ boxSizing: 'content-box', width: `${inputWidth}px` }}
            />
            <div ref={sizerRef} className="EditableField__autosize__sizer">
                {value}
            </div>
            <div ref={placeHolderSizerRef} className="EditableField__autosize__sizer">
                {placeholder}
            </div>
        </div>
    )
}
