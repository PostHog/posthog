import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

type DisplayTag = 'span' | 'div' | 'p' | 'h1' | 'h2'

interface InlineEditableProps {
    value: string
    onChange: (value: string) => void
    placeholder?: string
    multiline?: boolean
    /** Element used to render the non-editing display. Input mimics its styling. */
    as?: DisplayTag
    /** Class applied to both the display element and the editing input. */
    className?: string
    /** ARIA label for screen readers. */
    ariaLabel?: string
    /** Disable editing (e.g. when the survey is read-only). */
    disabled?: boolean
    /** Show invalid state — red outline plus tooltip-friendly title. */
    invalid?: boolean
    invalidReason?: string
    /** Optional data-attr forwarded to both display and input. */
    'data-attr'?: string
}

/**
 * Click-to-edit text primitive used by the hosted survey canvas. The display
 * and the editing input share the same className so the visual transition is
 * minimal — the canvas stays WYSIWYG even while editing.
 */
export function InlineEditable({
    value,
    onChange,
    placeholder,
    multiline = false,
    as = 'span',
    className,
    ariaLabel,
    disabled = false,
    invalid = false,
    invalidReason,
    'data-attr': dataAttr,
}: InlineEditableProps): JSX.Element {
    const [editing, setEditing] = useState(false)
    const [draft, setDraft] = useState(value)
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)

    useEffect(() => {
        if (!editing) {
            setDraft(value)
        }
    }, [value, editing])

    useEffect(() => {
        if (editing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [editing])

    const commit = (): void => {
        if (draft !== value) {
            onChange(draft)
        }
        setEditing(false)
    }

    const cancel = (): void => {
        setDraft(value)
        setEditing(false)
    }

    const sharedClass = clsx(
        'inline-editable',
        invalid && 'inline-editable--invalid',
        editing && 'inline-editable--editing',
        className
    )

    if (editing && !disabled) {
        const handleKey = (event: React.KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                cancel()
            } else if (event.key === 'Enter' && (!multiline || event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                commit()
            }
        }

        return multiline ? (
            <textarea
                ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                value={draft}
                placeholder={placeholder}
                aria-label={ariaLabel}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={handleKey}
                className={sharedClass}
                data-attr={dataAttr}
                // 1 row is the floor — `field-sizing: content` + scrollHeight
                // auto-grow take over from there. Without this the browser
                // defaults to 2 visible rows, which already feels too tall
                // for a one-line question title.
                rows={1}
            />
        ) : (
            <input
                ref={inputRef as React.RefObject<HTMLInputElement>}
                type="text"
                value={draft}
                placeholder={placeholder}
                aria-label={ariaLabel}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={handleKey}
                className={sharedClass}
                data-attr={dataAttr}
            />
        )
    }

    const DisplayTag = as
    const displayValue = value || placeholder || ''
    const isPlaceholder = !value

    return (
        <DisplayTag
            role={disabled ? undefined : 'button'}
            tabIndex={disabled ? undefined : 0}
            aria-label={ariaLabel}
            title={invalid ? invalidReason : undefined}
            onClick={disabled ? undefined : () => setEditing(true)}
            onKeyDown={
                disabled
                    ? undefined
                    : (event: React.KeyboardEvent) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              setEditing(true)
                          }
                      }
            }
            className={clsx(sharedClass, isPlaceholder && 'inline-editable--placeholder')}
            data-attr={dataAttr}
        >
            {displayValue}
        </DisplayTag>
    )
}
