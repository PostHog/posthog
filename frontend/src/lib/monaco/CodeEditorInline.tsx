import { CodeEditorProps } from 'lib/monaco/CodeEditor'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

export function CodeEditorInline(props: Omit<CodeEditorProps, 'height'>): JSX.Element {
    return (
        <CodeEditorResizeable
            {...props}
            minHeight="29px"
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
                ...props.options,
            }}
        />
    )
}
