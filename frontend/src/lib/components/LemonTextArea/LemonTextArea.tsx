import './LemonTextArea.scss'
import React, { useEffect, useRef } from 'react'
import clsx from 'clsx'
import TextareaAutosize from 'react-textarea-autosize'
import { Tabs } from 'antd'
import { IconMarkdown } from 'lib/components/icons'
import { TextCardBody } from 'lib/components/Cards/TextCard/TextCard'

export interface LemonTextAreaProps
    extends Pick<
        React.TextareaHTMLAttributes<HTMLTextAreaElement>,
        'onFocus' | 'onBlur' | 'maxLength' | 'autoFocus' | 'onKeyDown'
    > {
    id?: string
    value?: string
    defaultValue?: string
    placeholder?: string
    className?: string
    /** Whether input field is disabled */
    disabled?: boolean
    ref?: React.Ref<HTMLTextAreaElement>
    onChange?: (newValue: string) => void
    /** Callback called when Cmd + Enter (or Ctrl + Enter) is pressed.
     * This checks for Cmd/Ctrl, as opposed to LemonInput, to avoid blocking multi-line input. */
    onPressCmdEnter?: (newValue: string) => void
    minRows?: number
    maxRows?: number
    rows?: number
}

/** A `textarea` component for multi-line text. */
export const LemonTextArea = React.forwardRef<HTMLTextAreaElement, LemonTextAreaProps>(function _LemonTextArea(
    { className, onChange, onFocus, onBlur, onPressCmdEnter: onPressEnter, minRows = 3, onKeyDown, ...textProps },
    ref
): JSX.Element {
    const _ref = useRef<HTMLTextAreaElement | null>(null)
    const textRef = ref || _ref

    return (
        <TextareaAutosize
            minRows={minRows}
            ref={textRef}
            className={clsx('LemonTextArea', className)}
            onKeyDown={(e) => {
                if (onPressEnter && e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    onPressEnter(textProps.value?.toString() ?? '')
                }

                onKeyDown?.(e)
            }}
            onChange={(event) => {
                onChange?.(event.currentTarget.value ?? '')
            }}
            {...textProps}
        />
    )
})

interface LemonTextMarkdownProps {
    'data-attr'?: string
    value: string
    onChange: (s: string) => void
}

export function LemonTextMarkdown({ value, onChange, ...editAreaProps }: LemonTextMarkdownProps): JSX.Element {
    const [drag, setDrag] = React.useState(false)
    const [filename, setFilename] = React.useState('')
    const dropRef = React.createRef<HTMLDivElement>()
    let dragCounter = 0

    const handleDrag = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
    }

    const handleDragIn = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounter++
        if (e.dataTransfer?.items && e.dataTransfer.items.length > 0) {setDrag(true)}
    }

    const handleDragOut = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        dragCounter--
        if (dragCounter === 0) {setDrag(false)}
    }

    const handleDrop = (e: DragEvent): void => {
        e.preventDefault()
        e.stopPropagation()
        setDrag(false)
        if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
            // onDrop(e.dataTransfer.files[0])
            setFilename(e.dataTransfer.files[0].name)
            console.log(e.dataTransfer.files[0].name)
            e.dataTransfer.clearData()
            dragCounter = 0
        }
    }

    useEffect(() => {
        const div = dropRef.current
        if (!div) {
            return
        } else {
            div.addEventListener('dragenter', handleDragIn)
            div.addEventListener('dragleave', handleDragOut)
            div.addEventListener('dragover', handleDrag)
            div.addEventListener('drop', handleDrop)
            return () => {
                div?.removeEventListener('dragenter', handleDragIn)
                div?.removeEventListener('dragleave', handleDragOut)
                div?.removeEventListener('dragover', handleDrag)
                div?.removeEventListener('drop', handleDrop)
            }
        }
    }, [])

    return (
        <Tabs>
            <Tabs.TabPane tab="Write" key="write-card" destroyInactiveTabPane={true}>
                <div
                    ref={dropRef}
                    className={clsx(
                        'LemonTextMarkdown',
                        drag ? 'filedrop drag' : filename ? 'filedrop ready' : 'filedrop'
                    )}
                >
                    <LemonTextArea
                        {...editAreaProps}
                        autoFocus
                        value={value}
                        onChange={(newValue) => onChange(newValue)}
                    />
                    <div className="text-muted inline-flex items-center space-x-1">
                        <IconMarkdown className={'text-2xl'} />
                        <span>Markdown formatting support</span>
                    </div>
                </div>
            </Tabs.TabPane>
            <Tabs.TabPane tab="Preview" key={'preview-card'}>
                <TextCardBody text={value} />
            </Tabs.TabPane>
        </Tabs>
    )
}
