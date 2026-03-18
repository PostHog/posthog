import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { RichMarkdownEditor } from './RichMarkdownEditor'

const setContentMock = jest.fn()

const fakeChain = {
    focus: () => fakeChain,
    undo: () => fakeChain,
    redo: () => fakeChain,
    toggleHeading: () => fakeChain,
    toggleBold: () => fakeChain,
    toggleItalic: () => fakeChain,
    toggleUnderline: () => fakeChain,
    toggleCode: () => fakeChain,
    toggleCodeBlock: () => fakeChain,
    toggleBlockquote: () => fakeChain,
    setColor: () => fakeChain,
    unsetColor: () => fakeChain,
    toggleBulletList: () => fakeChain,
    toggleOrderedList: () => fakeChain,
    toggleTaskList: () => fakeChain,
    setTextAlign: () => fakeChain,
    setLink: () => fakeChain,
    unsetLink: () => fakeChain,
    setImage: () => fakeChain,
    insertContent: () => fakeChain,
    run: () => true,
}

const fakeEditor = {
    commands: {
        focus: jest.fn(),
        setContent: setContentMock,
    },
    getJSON: jest.fn(() => ({ type: 'doc' })),
    chain: () => fakeChain,
    can: () => ({
        chain: () => ({
            focus: () => ({
                undo: () => ({ run: () => true }),
                redo: () => ({ run: () => true }),
            }),
        }),
    }),
    isActive: jest.fn(() => false),
    getAttributes: jest.fn(() => ({})),
    on: jest.fn(),
    off: jest.fn(),
    view: {
        dom: document.createElement('div'),
    },
}

jest.mock('lib/components/RichContentEditor', () => ({
    useRichContentEditor: jest.fn(() => fakeEditor),
}))

jest.mock('lib/hooks/useUploadFiles', () => ({
    useUploadFiles: () => ({
        setFilesToUpload: jest.fn(),
        filesToUpload: [],
        uploading: false,
    }),
}))

jest.mock('@tiptap/react', () => ({
    EditorContent: ({ className, ...props }: any) => <div className={className} {...props} />,
}))

describe('RichMarkdownEditor', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows destructive counter styling when max length is exceeded', () => {
        render(
            <RichMarkdownEditor
                value="123456789"
                maxLength={5}
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => '123456789'}
            />
        )

        const counter = screen.getByText('9/5 characters (limit reached)')
        expect(counter).toBeInTheDocument()
        expect(counter).toHaveClass('text-danger')
    })

    it('renders custom preview output when preview tab selected', () => {
        render(
            <RichMarkdownEditor
                value="hello **world**"
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => 'hello **world**'}
                renderPreview={() => <div>Custom Preview Render</div>}
            />
        )

        fireEvent.click(screen.getAllByRole('tab', { name: 'Preview' })[0])
        expect(screen.getByText('Custom Preview Render')).toBeInTheDocument()
    })

    it('syncs editor content when controlled value changes', () => {
        let currentMarkdown = 'old value'
        const markdownToDoc = jest.fn((markdown: string | null | undefined) => ({
            type: 'doc',
            content: markdown ? [{ type: 'paragraph' }] : [],
        }))
        const docToMarkdown = jest.fn(() => currentMarkdown)

        const { rerender } = render(
            <RichMarkdownEditor
                value="old value"
                extensions={[]}
                markdownToDoc={markdownToDoc}
                docToMarkdown={docToMarkdown}
            />
        )

        currentMarkdown = 'stale editor value'
        rerender(
            <RichMarkdownEditor
                value="new value"
                extensions={[]}
                markdownToDoc={markdownToDoc}
                docToMarkdown={docToMarkdown}
            />
        )

        expect(markdownToDoc).toHaveBeenCalledWith('new value')
        expect(setContentMock).toHaveBeenCalledWith(expect.any(Object), { emitUpdate: false })
    })

    it('syncs latest markdown on form submit capture', () => {
        const onChange = jest.fn()
        const markdownToDoc = jest.fn(() => ({ type: 'doc', content: [] }))
        const initialDocToMarkdown = jest.fn(() => 'old value')
        const submitDocToMarkdown = jest.fn(() => 'latest resized markdown')

        const { container, rerender } = render(
            <form data-attr="editor-form">
                <RichMarkdownEditor
                    value="old value"
                    onChange={onChange}
                    extensions={[]}
                    markdownToDoc={markdownToDoc}
                    docToMarkdown={initialDocToMarkdown}
                />
            </form>
        )

        const editorDom = container.querySelector('[data-attr="rich-markdown-editor-area"]') as HTMLDivElement
        fakeEditor.view.dom = editorDom

        rerender(
            <form data-attr="editor-form">
                <RichMarkdownEditor
                    value="old value"
                    onChange={onChange}
                    extensions={[]}
                    markdownToDoc={markdownToDoc}
                    docToMarkdown={submitDocToMarkdown}
                />
            </form>
        )

        fireEvent.submit(container.querySelector('form') as HTMLFormElement)

        expect(onChange).toHaveBeenCalledWith('latest resized markdown')
    })
})
