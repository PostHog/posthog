import { CodeEditorProps } from 'lib/monaco/CodeEditor'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { useEffect, useMemo } from 'react'

export interface CodeEditorInlineProps extends Omit<CodeEditorProps, 'height'> {
    minHeight?: string
}
export function CodeEditorInline(props: CodeEditorInlineProps): JSX.Element {
    const monacoRoot = useMemo(() => {
        const body = (typeof document !== 'undefined' && document.getElementsByTagName('body')[0]) || null
        const monacoRoot = document.createElement('div')
        monacoRoot.classList.add('monaco-editor')
        monacoRoot.style.zIndex = 'var(--z-tooltip)'
        body?.appendChild(monacoRoot)
        return monacoRoot
    }, [])
    useEffect(() => {
        return () => {
            monacoRoot?.remove()
        }
    }, [])
    return (
        <CodeEditorResizeable
            minHeight="29px"
            {...props}
            options={{
                // Note: duplicate anything you add here with its default into <CodeEditor />
                lineNumbers: 'off',
                minimap: { enabled: false },
                folding: false,
                wordWrap: 'on',
                renderLineHighlight: 'none',
                scrollbar: { vertical: 'auto', horizontal: 'hidden' },
                overviewRulerBorder: false,
                hideCursorInOverviewRuler: true,
                overviewRulerLanes: 0,
                tabFocusMode: true,
                fixedOverflowWidgets: true,
                overflowWidgetsDomNode: monacoRoot,
                ...props.options,
            }}
        />
    )
}
