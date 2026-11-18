import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { MetadataHeader } from './MetadataHeader'

describe('MetadataHeader', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders a string model', () => {
        render(
            <Provider>
                <MetadataHeader model="GPT-4o" />
            </Provider>
        )

        expect(screen.getByText('GPT-4o')).toBeInTheDocument()
    })

    const lenientTokenCounts: [string, unknown, unknown][] = [
        ['string counts', '12', '512'],
        ['an object-shaped output count', 12, { total: 512, noCache: 512, cacheRead: 0 }],
    ]

    it.each(lenientTokenCounts)('renders token usage for %s', (_label, inputTokens, outputTokens) => {
        render(
            <Provider>
                <MetadataHeader inputTokens={inputTokens} outputTokens={outputTokens} />
            </Provider>
        )

        expect(screen.getByText('12 prompt tokens → 512 completion tokens (∑ 524)')).toBeInTheDocument()
    })

    const nonStringModels: [string, unknown][] = [
        ['number', 4],
        ['boolean', true],
        ['object', { name: 'gpt-4o' }],
        ['null', null],
        ['undefined', undefined],
    ]

    it.each(nonStringModels)('does not throw for a %s model', (_label, model) => {
        const { container } = render(
            <Provider>
                <MetadataHeader model={model as string} />
            </Provider>
        )

        expect(container.textContent).toBe('')
    })
})
