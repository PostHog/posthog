import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { JSONValueDisplay } from './JSONValueDisplay'

// react-json-view is loaded via React.lazy, so the first render suspends on a code-split chunk.
// Under CI contention that resolve can exceed waitFor's 1s default, so give it headroom.
const JSON_VIEWER_TIMEOUT_MS = 5000

describe('JSONValueDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderValue(value: unknown): ReturnType<typeof render> {
        return render(
            <Provider>
                <JSONValueDisplay value={value} />
            </Provider>
        )
    }

    it('renders JSON arrays with the JSON viewer', async () => {
        const { container } = renderValue([{ role: 'user', content: [{ type: 'text', text: 'hello' }] }])

        await waitFor(
            () => {
                expect(container.querySelector('.react-json-view')).toBeInTheDocument()
            },
            { timeout: JSON_VIEWER_TIMEOUT_MS }
        )
        expect(container.textContent).toContain('role')
        expect(container.textContent).toContain('hello')
    })

    it('parses stringified JSON arrays before rendering', async () => {
        const { container } = renderValue(JSON.stringify([{ role: 'user', content: 'hello' }]))

        await waitFor(
            () => {
                expect(container.querySelector('.react-json-view')).toBeInTheDocument()
            },
            { timeout: JSON_VIEWER_TIMEOUT_MS }
        )
        expect(container.textContent).toContain('role')
        expect(container.textContent).toContain('hello')
    })

    it('keeps bracket-prefixed plain text readable', () => {
        const { container } = renderValue('[Thinking: not JSON]')

        expect(container.querySelector('.react-json-view')).not.toBeInTheDocument()
        expect(container.textContent).toContain('[Thinking: not JSON]')
    })

    it('truncates pathologically long string values by default', async () => {
        // Guards against huge inline values (LLM prompts/completions, base64 blobs) thrashing render.
        const hugeValue = 'X'.repeat(20000)
        const { container } = renderValue({ prompt: hugeValue })

        await waitFor(() => {
            expect(container.querySelector('.react-json-view')).toBeInTheDocument()
        })
        // The full string is not rendered, but a truncated prefix still is (expandable on click).
        expect(container.textContent).not.toContain('X'.repeat(20000))
        expect(container.textContent).toContain('X'.repeat(10000))
    })
})
