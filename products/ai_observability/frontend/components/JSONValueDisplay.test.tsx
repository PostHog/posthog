import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { JSONValueDisplay } from './JSONValueDisplay'

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

        await waitFor(() => {
            expect(container.querySelector('.react-json-view')).toBeInTheDocument()
        })
        expect(container.textContent).toContain('role')
        expect(container.textContent).toContain('hello')
    })

    it('parses stringified JSON arrays before rendering', async () => {
        const { container } = renderValue(JSON.stringify([{ role: 'user', content: 'hello' }]))

        await waitFor(() => {
            expect(container.querySelector('.react-json-view')).toBeInTheDocument()
        })
        expect(container.textContent).toContain('role')
        expect(container.textContent).toContain('hello')
    })

    it('keeps bracket-prefixed plain text readable', () => {
        const { container } = renderValue('[Thinking: not JSON]')

        expect(container.querySelector('.react-json-view')).not.toBeInTheDocument()
        expect(container.textContent).toContain('[Thinking: not JSON]')
    })
})
