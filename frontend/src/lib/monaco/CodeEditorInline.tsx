import { CodeEditorProps } from 'lib/monaco/CodeEditor'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

export interface CodeEditorInlineProps extends Omit<CodeEditorProps, 'height'> {
    minHeight?: string
}
export function CodeEditorInline(props: CodeEditorInlineProps): JSX.Element {
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
                ...props.options,
            }}
        />
    )
}
