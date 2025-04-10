// adapted from https://github.com/react-monaco-editor/react-monaco-editor/blob/d2fd2521e0557c880dec93acaab9a087f025426c/src/diff.tsx

import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react'

interface MonacoDiffEditorProps {
    width?: number | string
    height?: number | string
    value?: string | null
    original?: string | null
    modified: string | null
    language?: string
    theme?: string | null
    options?: monaco.editor.IDiffEditorConstructionOptions
    onChange?: (value: string, event: monaco.editor.IModelContentChangedEvent) => void
    className?: string | null
    originalUri?: (monaco: typeof import('monaco-editor')) => monaco.Uri
    modifiedUri?: (monaco: typeof import('monaco-editor')) => monaco.Uri
}

function processSize(size: number | string): string {
    return !/^\d+$/.test(size as string) ? (size as string) : `${size}px`
}

function MonacoDiffEditor(
    {
        width = '100%',
        height = '100%',
        value = '',
        original = '',
        modified = '',
        language = 'javascript',
        theme = null,
        options = {},
        onChange = () => {},
        className = null,
        originalUri,
        modifiedUri,
    }: MonacoDiffEditorProps,
    ref: React.ForwardedRef<{ editor: monaco.editor.IStandaloneDiffEditor | null }>
): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<monaco.editor.IStandaloneDiffEditor | null>(null)
    const subscriptionRef = useRef<monaco.IDisposable | null>(null)

    // Calculate height based on content
    const calculatedHeight = useMemo(() => {
        if (height !== '100%') {
            return height
        }

        // Count lines in original and modified content
        const originalLines = (original || '').split('\n').length
        const modifiedLines = (modified || '').split('\n').length

        // Use the larger of the two, with a minimum of 5 lines and a maximum of 30
        const lineCount = Math.max(5, Math.min(30, Math.max(originalLines, modifiedLines)))

        // Approximate line height is 18px, plus some padding
        return `${lineCount * 18 + 18}px`
    }, [height, original, modified])

    // Initialize editor
    useEffect(() => {
        if (!containerRef.current) {
            return
        }

        editorRef.current = monaco.editor.createDiffEditor(containerRef.current, {
            ...(className ? { extraEditorClassName: className } : {}),
            ...options,
            ...(theme ? { theme } : {}),
            readOnly: true,
        })

        // Create models
        const originalModel = monaco.editor.createModel(original ?? '', language, originalUri?.(monaco))
        const modifiedModel = monaco.editor.createModel(value ?? '', language, modifiedUri?.(monaco))

        editorRef.current.setModel({ original: originalModel, modified: modifiedModel })

        // Set up change listener
        subscriptionRef.current = modifiedModel.onDidChangeContent((event) => {
            onChange(modifiedModel.getValue(), event)
        })

        // Cleanup
        return () => {
            const model = editorRef.current?.getModel()
            if (editorRef.current && model) {
                const { original: originalEditor, modified } = model
                editorRef.current.dispose()
                originalEditor.dispose()
                modified.dispose()
            }
            subscriptionRef.current?.dispose()
        }
    }, []) // Run once on mount

    // Update editor options
    useEffect(() => {
        editorRef.current?.updateOptions({
            ...(className ? { extraEditorClassName: className } : {}),
            ...options,
        })
    }, [className, options])

    // Update layout on size changes
    useEffect(() => {
        editorRef.current?.layout()
    }, [width, calculatedHeight])

    // Update language
    useEffect(() => {
        const model = editorRef.current?.getModel()
        if (model) {
            const { original: originalEditor, modified } = model
            monaco.editor.setModelLanguage(originalEditor, language)
            monaco.editor.setModelLanguage(modified, language)
        }
    }, [language])

    // Update value
    useEffect(() => {
        const model = editorRef.current?.getModel()
        if (model) {
            const { modified: modifiedEditor } = model
            modifiedEditor.setValue(modified ?? '')
        }
    }, [modified])

    // Update theme
    useEffect(() => {
        if (theme) {
            monaco.editor.setTheme(theme)
        }
    }, [theme])

    // Update original content
    useEffect(() => {
        const model = editorRef.current?.getModel()
        if (model) {
            const { original: originalEditor } = model
            originalEditor.setValue(original ?? '')
        }
    }, [original])

    // Expose editor instance via ref
    useImperativeHandle(ref, () => ({
        get editor() {
            return editorRef.current
        },
    }))

    return (
        <div
            ref={containerRef}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: processSize(width),
                height: processSize(calculatedHeight),
            }}
            className="react-monaco-editor-container"
        />
    )
}

export default forwardRef(MonacoDiffEditor)
