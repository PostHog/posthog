import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LazyLemonRichContentEditor, LazyTextContent } from './LazyRichContent'

let mockFailImports = true
const mockChunkLoadError = (): Error => new Error('Failed to fetch dynamically imported module: /static/chunk.js')

// A getter makes the import fail while the flag is set, the way a chunk fetch fails, and succeed after.
jest.mock('lib/components/Cards/TextCard/TextContent', () => ({
    __esModule: true,
    get TextContent() {
        if (mockFailImports) {
            throw mockChunkLoadError()
        }
        return ({ text }: { text: string }) => <div>rich {text}</div>
    },
}))
jest.mock('./LemonRichContentEditor', () => ({
    __esModule: true,
    get LemonRichContentEditor() {
        if (mockFailImports) {
            throw mockChunkLoadError()
        }
        return () => <div>rich editor</div>
    },
    RichContentPreview: () => null,
}))

describe('LazyRichContent', () => {
    afterEach(cleanup)

    it('keeps a failed chunk local: text falls back to markdown, the editor offers a retry', async () => {
        render(
            <>
                <LazyTextContent text="Hello **there**" />
                <LazyLemonRichContentEditor logicKey="test" onCreate={() => {}} />
            </>
        )

        expect(await screen.findByText("Couldn't load the editor.", undefined, { timeout: 5000 })).toBeInTheDocument()
        expect(screen.getByText('Hello **there**')).toBeInTheDocument()

        mockFailImports = false
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

        expect(await screen.findByText('rich editor', undefined, { timeout: 5000 })).toBeInTheDocument()
    })
})
