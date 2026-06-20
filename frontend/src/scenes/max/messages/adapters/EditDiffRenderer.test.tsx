import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SandboxToolCallMessage } from '../../maxTypes'
import { EditDiffRenderer } from './EditDiffRenderer'

// Monaco can't render in jsdom — stand it in for a marker that echoes the diff props we care about.
jest.mock('lib/components/MonacoDiffEditor', () => ({
    __esModule: true,
    default: ({
        original,
        modified,
        language,
        theme,
    }: {
        original?: string
        modified?: string
        language?: string
        theme?: string
    }) => (
        <div
            data-attr="monaco-diff"
            data-original={original}
            data-modified={modified}
            data-language={language}
            data-theme={theme}
        />
    ),
}))

// Force the lazy-mount gate open so the editor instantiates.
jest.mock('react-intersection-observer', () => ({
    useInView: () => ({ ref: () => {}, inView: true }),
}))

// Drive the app theme without mounting themeLogic (and its scene/user deps). The arrow reads
// `mockDarkMode` lazily at render time, so flipping it per test works.
let mockDarkMode = false
jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({ isDarkModeOn: mockDarkMode }),
}))

function makeMessage(overrides: Partial<SandboxToolCallMessage> = {}): SandboxToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Edit',
        rawServerName: 'posthog',
        rawToolName: 'Edit',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('EditDiffRenderer', () => {
    afterEach(() => {
        cleanup()
        mockDarkMode = false
    })

    it('renders an inline diff with +/- stats for an Edit with a diff block', () => {
        const message = makeMessage({
            title: 'Edit `foo.ts`',
            content: [{ type: 'diff', path: 'foo.ts', oldText: 'a\nb', newText: 'a\nb\nc' }],
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        const editor = screen.getByTestId('monaco-diff')
        expect(editor).toBeInTheDocument()
        expect(editor).toHaveAttribute('data-original', 'a\nb')
        expect(editor).toHaveAttribute('data-modified', 'a\nb\nc')
        expect(editor).toHaveAttribute('data-language', 'typescript')
        expect(editor).toHaveAttribute('data-theme', 'vs')
        expect(screen.getByText('foo.ts')).toBeInTheDocument()
        expect(screen.getByText('+1')).toBeInTheDocument()
        expect(screen.getByText('-0')).toBeInTheDocument()
    })

    it('renders one editor per diff block for a MultiEdit', () => {
        const message = makeMessage({
            resolvedKey: 'MultiEdit',
            content: [
                { type: 'diff', path: 'foo.ts', oldText: 'a', newText: 'b' },
                { type: 'content', content: { type: 'diff', path: 'foo.ts', oldText: 'b', newText: 'c' } },
            ],
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        expect(screen.getAllByTestId('monaco-diff')).toHaveLength(2)
    })

    it('shows all-added stats and an empty original for a new file (Write)', () => {
        const message = makeMessage({
            resolvedKey: 'Write',
            content: [{ type: 'diff', path: 'new.py', oldText: null, newText: 'print(1)\nprint(2)' }],
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        const editor = screen.getByTestId('monaco-diff')
        expect(editor).toHaveAttribute('data-original', '')
        expect(editor).toHaveAttribute('data-language', 'python')
        expect(screen.getByText('+2')).toBeInTheDocument()
    })

    it('resolves filename and language from rawInput.file_path when the diff block has no path', () => {
        const message = makeMessage({
            content: [{ type: 'diff', oldText: 'a', newText: 'b' }],
            rawInput: { file_path: 'main.go' },
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        expect(screen.getByText('main.go')).toBeInTheDocument()
        expect(screen.getByTestId('monaco-diff')).toHaveAttribute('data-language', 'go')
    })

    it('falls back to the plain tool card (no editor) when there is no diff block', () => {
        const message = makeMessage({ title: 'Edit `foo.ts`', content: [{ type: 'text', text: 'no diff yet' }] })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
        // The standard tool card still renders its header.
        expect(screen.getByText('Edit `foo.ts`')).toBeInTheDocument()
    })

    it('uses the dark Monaco theme when the app is in dark mode', () => {
        mockDarkMode = true
        const message = makeMessage({ content: [{ type: 'diff', path: 'foo.ts', oldText: 'a', newText: 'b' }] })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        expect(screen.getByTestId('monaco-diff')).toHaveAttribute('data-theme', 'vs-dark')
    })
})
