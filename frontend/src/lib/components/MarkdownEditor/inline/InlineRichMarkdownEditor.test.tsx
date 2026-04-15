import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useUploadFiles } from 'lib/hooks/useUploadFiles'

import { initKeaTests } from '~/test/init'

import { InlineRichMarkdownEditor } from './InlineRichMarkdownEditor'

jest.mock('lib/hooks/useUploadFiles')

const setContentMock = jest.fn()

const fakeChain = {
    focus: () => fakeChain,
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
    isActive: jest.fn(() => false),
    getAttributes: jest.fn(() => ({})),
    on: jest.fn(),
    off: jest.fn(),
    isDestroyed: false,
    isInitialized: true,
    editorView: {
        dom: document.createElement('div'),
    },
}

jest.mock('lib/components/RichContentEditor', () => ({
    useRichContentEditor: jest.fn(() => fakeEditor),
}))

const mockUseUploadFiles = jest.mocked(useUploadFiles)

jest.mock('@tiptap/react', () => ({
    ...jest.requireActual('@tiptap/react'),
    EditorContent: ({ className, ...props }: any) => <div className={className} {...props} />,
}))

jest.mock('@tiptap/react/menus', () => ({
    BubbleMenu: ({ children }: any) => <div data-attr="inline-bubble-menu">{children}</div>,
}))

describe('InlineRichMarkdownEditor', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        fakeEditor.editorView.dom = document.createElement('div')
        mockUseUploadFiles.mockReturnValue({
            setFilesToUpload: jest.fn(),
            filesToUpload: [],
            uploading: false,
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('shows destructive counter styling when max length is exceeded', () => {
        render(
            <InlineRichMarkdownEditor
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

    it('hides character count footer when showCharacterCount is false', () => {
        render(
            <InlineRichMarkdownEditor
                value="hello"
                showCharacterCount={false}
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => 'hello'}
            />
        )

        expect(screen.queryByText(/characters/)).not.toBeInTheDocument()
    })

    it('mounts bubble menu after editor is ready', async () => {
        render(
            <InlineRichMarkdownEditor
                value=""
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => ''}
            />
        )

        await waitFor(() => {
            expect(screen.getByTestId('inline-bubble-menu')).toBeInTheDocument()
        })
    })

    it('syncs editor content when controlled value changes', () => {
        let currentMarkdown = 'old value'
        const markdownToDoc = jest.fn((markdown: string | null | undefined) => ({
            type: 'doc',
            content: markdown ? [{ type: 'paragraph' }] : [],
        }))
        const docToMarkdown = jest.fn(() => currentMarkdown)

        const { rerender } = render(
            <InlineRichMarkdownEditor
                value="old value"
                extensions={[]}
                markdownToDoc={markdownToDoc}
                docToMarkdown={docToMarkdown}
            />
        )

        currentMarkdown = 'stale editor value'
        rerender(
            <InlineRichMarkdownEditor
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
            <form data-attr="inline-editor-form">
                <InlineRichMarkdownEditor
                    value="old value"
                    onChange={onChange}
                    extensions={[]}
                    markdownToDoc={markdownToDoc}
                    docToMarkdown={initialDocToMarkdown}
                    dataAttr="inline-rich-markdown-editor-area"
                />
            </form>
        )

        const editorDom = container.querySelector('[data-attr="inline-rich-markdown-editor-area"]') as HTMLDivElement
        Object.assign(fakeEditor.editorView, { dom: editorDom })

        rerender(
            <form data-attr="inline-editor-form">
                <InlineRichMarkdownEditor
                    value="old value"
                    onChange={onChange}
                    extensions={[]}
                    markdownToDoc={markdownToDoc}
                    docToMarkdown={submitDocToMarkdown}
                    dataAttr="inline-rich-markdown-editor-area"
                />
            </form>
        )

        fireEvent.submit(container.querySelector('form') as HTMLFormElement)

        expect(onChange).toHaveBeenCalledWith('latest resized markdown')
    })

    it('calls focus when autoFocus is true and editor dom is available', async () => {
        render(
            <InlineRichMarkdownEditor
                value=""
                autoFocus
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => ''}
            />
        )

        await waitFor(() => {
            expect(fakeEditor.commands.focus).toHaveBeenCalled()
        })
    })

    it('applies custom className to shell', () => {
        const { container } = render(
            <InlineRichMarkdownEditor
                value=""
                className="my-inline-editor"
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => ''}
            />
        )

        expect(container.querySelector('.my-inline-editor')).toBeInTheDocument()
    })

    it('accepts showSlashCommands without throwing', () => {
        const { container } = render(
            <InlineRichMarkdownEditor
                value=""
                showSlashCommands
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => ''}
            />
        )

        expect(container.querySelector('[data-attr="inline-rich-markdown-editor-area"]')).toBeInTheDocument()
    })

    it('feeds the slash image file input into the markdown upload hook', () => {
        const setFilesToUpload = jest.fn()
        mockUseUploadFiles.mockReturnValue({
            setFilesToUpload,
            filesToUpload: [],
            uploading: false,
        })

        const { container } = render(
            <InlineRichMarkdownEditor
                value=""
                showBubbleImageUpload
                showSlashCommands
                extensions={[]}
                markdownToDoc={() => ({ type: 'doc', content: [] })}
                docToMarkdown={() => ''}
            />
        )

        const input = container.querySelector(
            '[data-attr="inline-rich-markdown-slash-image-input"]'
        ) as HTMLInputElement
        const file = new File(['x'], 'shot.png', { type: 'image/png' })
        fireEvent.change(input, { target: { files: [file] } })

        expect(setFilesToUpload).toHaveBeenCalledWith([file])
    })
})
