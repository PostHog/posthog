import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'

export interface CodeEditorResizableProps extends Omit<CodeEditorProps, 'height'> {
    height?: number
    minHeight?: string | number
    maxHeight?: string | number
    editorClassName?: string
    embedded?: boolean
    showDiffActions?: boolean
    onAcceptChanges?: () => void
    onRejectChanges?: () => void
    originalValue?: string
}

export function CodeEditorResizeable({
    height: defaultHeight,
    minHeight = '5rem',
    maxHeight = '90vh',
    className,
    editorClassName,
    embedded = false,
    showDiffActions = false,
    onAcceptChanges,
    onRejectChanges,
    originalValue,
    ...props
}: CodeEditorResizableProps): JSX.Element {
    const [height, setHeight] = useState(defaultHeight)
    const [manualHeight, setManualHeight] = useState<number | undefined>(defaultHeight)

    const ref = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        const value = typeof props.value !== 'string' ? JSON.stringify(props.value, null, 2) : props.value
        const lineCount = (value?.split('\n').length ?? 1) + 1
        const lineHeight = 18
        setHeight(lineHeight * lineCount)
    }, [props.value])

    return (
        <div
            ref={ref}
            className={clsx('relative CodeEditorResizeable', !embedded ? 'w-full rounded border' : '', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                minHeight,
                maxHeight,
                height: manualHeight ?? height,
            }}
        >
            <AutoSizer disableWidth>
                {({ height }) => (
                    <CodeEditor
                        {...props}
                        className={editorClassName}
                        height={height - 2} // Account for border
                        originalValue={originalValue}
                    />
                )}
            </AutoSizer>

            {showDiffActions && (
                <div className="flex absolute top-2 right-2 z-20 gap-1 p-1 bg-white rounded-lg border shadow-sm">
                    <LemonButton
                        status="danger"
                        icon={<IconX />}
                        onClick={onRejectChanges}
                        tooltipPlacement="top"
                        size="small"
                    >
                        Reject
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        icon={<IconCheck color="var(--success)" />}
                        onClick={onAcceptChanges}
                        tooltipPlacement="top"
                        size="small"
                    >
                        Accept
                    </LemonButton>
                </div>
            )}

            {/* Using a standard resize css means we need overflow-hidden which hides parts of the editor unnecessarily */}
            <div
                className="overflow-hidden absolute right-0 bottom-0 z-20 w-5 h-5 resize-y cursor-s-resize"
                onMouseDown={(e) => {
                    const startY = e.clientY
                    const startHeight = ref.current?.clientHeight ?? 0
                    const onMouseMove = (event: MouseEvent): void => {
                        setManualHeight(startHeight + event.clientY - startY)
                    }
                    const onMouseUp = (): void => {
                        window.removeEventListener('mousemove', onMouseMove)
                        window.removeEventListener('mouseup', onMouseUp)
                    }
                    window.addEventListener('mousemove', onMouseMove)
                    window.addEventListener('mouseup', onMouseUp)
                }}
            />
        </div>
    )
}
