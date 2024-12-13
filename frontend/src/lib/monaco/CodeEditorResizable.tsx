import clsx from 'clsx'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { useEffect, useRef, useState } from 'react'
import AutoSizer from 'react-virtualized/dist/es/AutoSizer'

export interface CodeEditorResizableProps extends Omit<CodeEditorProps, 'height'> {
    height?: number
    minHeight?: string | number
    maxHeight?: string | number
    editorClassName?: string
    embedded?: boolean
}

export function CodeEditorResizeable({
    height: defaultHeight,
    minHeight = '5rem',
    maxHeight = '90vh',
    className,
    editorClassName,
    embedded = false,
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
            className={clsx('CodeEditorResizeable relative', !embedded ? 'border rounded w-full' : '', className)}
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
                    />
                )}
            </AutoSizer>

            {/* Using a standard resize css means we need overflow-hidden which hides parts of the editor unnecessarily */}
            <div
                className="absolute bottom-0 right-0 z-10 resize-y h-5 w-5 cursor-s-resize overflow-hidden"
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
