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
