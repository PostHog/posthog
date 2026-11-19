import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LazyLemonRichContentEditor, LazyTextContent } from './LazyRichContent'

let mockFailImports = true
const mockChunkLoadError = (): Error => new Error('Failed to fetch dynamically imported module: /static/chunk.js')

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

    it('offers a page reload when a retry fails too', async () => {
        render(<LazyLemonRichContentEditor logicKey="test" onCreate={() => {}} />)

        fireEvent.click(await screen.findByText('Try again', undefined, { timeout: 5000 }))

        expect(await screen.findByText('Reload page', undefined, { timeout: 5000 })).toBeInTheDocument()
    })

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
        fireEvent.click(screen.getByText('Try again'))

        expect(await screen.findByText('rich editor', undefined, { timeout: 5000 })).toBeInTheDocument()
    })
})
