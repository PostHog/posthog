import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import { NodeViewContent, NodeViewProps, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { common, createLowlight } from 'lowlight'

import { LemonSelect } from '@posthog/lemon-ui'

const lowlight = createLowlight(common)

const LANGUAGES = [
    { value: '', label: 'Plain text' },
    { value: 'javascript', label: 'JavaScript' },
    { value: 'typescript', label: 'TypeScript' },
    { value: 'python', label: 'Python' },
    { value: 'html', label: 'HTML' },
    { value: 'css', label: 'CSS' },
    { value: 'json', label: 'JSON' },
    { value: 'sql', label: 'SQL' },
    { value: 'bash', label: 'Bash' },
    { value: 'go', label: 'Go' },
    { value: 'rust', label: 'Rust' },
    { value: 'java', label: 'Java' },
    { value: 'ruby', label: 'Ruby' },
    { value: 'php', label: 'PHP' },
    { value: 'swift', label: 'Swift' },
    { value: 'kotlin', label: 'Kotlin' },
    { value: 'yaml', label: 'YAML' },
    { value: 'markdown', label: 'Markdown' },
    { value: 'xml', label: 'XML' },
]

function CodeBlockComponent({ node, updateAttributes }: NodeViewProps): JSX.Element {
    const language = (node.attrs.language as string) || ''

    return (
        <NodeViewWrapper className="code-block-wrapper">
            <div className="code-block-lang-select" contentEditable={false}>
                <LemonSelect
                    size="xsmall"
                    value={language}
                    onChange={(value) => updateAttributes({ language: value || '' })}
                    options={LANGUAGES}
                />
            </div>
            <pre>
                <code>
                    <NodeViewContent />
                </code>
            </pre>
        </NodeViewWrapper>
    )
}

export const CodeBlockExtension = CodeBlockLowlight.extend({
    addNodeView() {
        return ReactNodeViewRenderer(CodeBlockComponent)
    },
}).configure({ lowlight })
