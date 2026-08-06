import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { getMatchedValue, MatchedValueBadge } from './MatchedValueBadge'
import { MenuFilterEntry } from './types'

function makeEntry(item: Record<string, any>): MenuFilterEntry {
    return {
        item,
        group: { type: 'log_attributes', name: 'Log attributes' },
        name: item.name ?? 'attr',
    } as unknown as MenuFilterEntry
}

describe('MatchedValueBadge', () => {
    afterEach(cleanup)

    it('renders the matched value when the item matched on value', () => {
        render(<MatchedValueBadge entry={makeEntry({ name: 'level', matchedOn: 'value', matchedValue: 'error' })} />)
        expect(screen.getByLabelText('Matched on value')).toHaveTextContent('error')
    })

    it('truncates long matched values', () => {
        const long = 'a'.repeat(40)
        render(<MatchedValueBadge entry={makeEntry({ name: 'level', matchedOn: 'value', matchedValue: long })} />)
        expect(screen.getByLabelText('Matched on value')).toHaveTextContent('…')
    })

    it.each([
        ['matched on name', { name: 'level', matchedOn: 'name', matchedValue: 'error' }],
        ['no matchedValue', { name: 'level', matchedOn: 'value' }],
        ['empty matchedValue', { name: 'level', matchedOn: 'value', matchedValue: '' }],
        ['plain attribute', { name: 'level' }],
    ])('renders nothing for %s', (_label, item) => {
        const { container } = render(<MatchedValueBadge entry={makeEntry(item)} />)
        expect(container).toBeEmptyDOMElement()
        expect(getMatchedValue(makeEntry(item))).toBeNull()
    })
})
