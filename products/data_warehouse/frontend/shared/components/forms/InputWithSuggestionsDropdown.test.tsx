import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { InputWithSuggestionsDropdown } from './InputWithSuggestionsDropdown'

describe('InputWithSuggestionsDropdown', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    const openPicker = (suggestions: string[]): void => {
        render(
            <InputWithSuggestionsDropdown
                value=""
                onChange={() => {}}
                suggestions={suggestions}
                data-attr="account"
                emptyMessage="Nothing is available."
                noMatchMessage={() => 'Nothing matches your filter.'}
            />
        )
        fireEvent.focus(document.querySelector('[data-attr="account"]')!)
    }

    // Callers that filter server-side hand back an empty `suggestions` list while a search term is
    // active, and the "nothing is available" wording there reads as a broken connection rather than
    // a filter that matched nothing.
    it('reports a filter that matched nothing rather than an empty source list', () => {
        openPicker([])
        expect(screen.getByText('Nothing is available.')).toBeInTheDocument()

        fireEvent.change(screen.getByPlaceholderText('Filter suggestions…'), { target: { value: 'abc' } })

        expect(screen.getByText('Nothing matches your filter.')).toBeInTheDocument()
        expect(screen.queryByText('Nothing is available.')).not.toBeInTheDocument()
    })
})
