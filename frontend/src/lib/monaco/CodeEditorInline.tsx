import { CodeEditorProps } from 'lib/monaco/CodeEditor'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

export function CodeEditorInline(props: Omit<CodeEditorProps, 'height'>): JSX.Element {
    return (
        <CodeEditorResizeable
            {...props}
            minHeight="29px"
            options={{
                lineNumbers: 'off',
                minimap: { enabled: false },
                folding: false,
                wordWrap: 'on',
                renderLineHighlight: 'none',
                scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                tabFocusMode: true,
                ...props.options,
            }}
        />
    )
}
