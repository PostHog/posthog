import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { FacetDefinition, FacetSearchValue, serializeFacetQuery } from './facetQuery'
import { FacetSearchBar } from './FacetSearchBar'

interface Item {
    name: string
    status: string
}

const FACETS: FacetDefinition<Item>[] = [
    {
        key: 'status',
        label: 'Status',
        description: 'Lifecycle',
        showOnFocus: true,
        getValues: (item) => [item.status],
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active' },
    { name: 'Renewal', status: 'draft' },
    { name: 'Promo', status: 'archived' },
]

function Harness({ initial }: { initial: FacetSearchValue }): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <div>
            <FacetSearchBar
                facets={FACETS}
                items={ITEMS}
                value={value}
                onChange={setValue}
                matchesText={(item, text) => item.name.toLowerCase().includes(text.toLowerCase())}
                placeholder="Search"
                dataAttr="test-search"
            />
            <output data-attr="query">{serializeFacetQuery(value.filters)}</output>
            <output data-attr="text">{value.text}</output>
            <button type="button" data-attr="after">
                After
            </button>
        </div>
    )
}

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('input[data-attr="test-search"]')!
const shown = (attr: string): string => document.querySelector(`[data-attr="${attr}"]`)?.textContent ?? ''
const listbox = (): Element | null => document.querySelector('[role="listbox"]')

describe('FacetSearchBar', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    const setup = (initial: FacetSearchValue = { filters: [], text: '' }): ReturnType<typeof userEvent.setup> => {
        render(<Harness initial={initial} />)
        return userEvent.setup()
    }

    it('Tab and → take the first filter row, never the search row', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('sta{ArrowDown}')
        expect(document.querySelector('[role="option"][aria-selected="true"]')).toHaveTextContent('Search for "sta"')

        await user.keyboard('{Tab}')
        expect(input()).toHaveValue('status:')
        expect(shown('text')).toEqual('')

        await user.keyboard('act{ArrowRight}')
        expect(shown('query')).toEqual('status:active')
        expect(input()).toHaveValue('')
        expect(input()).toHaveFocus()
    })

    it('Enter on the search row closes the popover and keeps the text', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('renew')
        expect(listbox()).not.toBeNull()

        await user.keyboard('{Enter}')
        expect(listbox()).toBeNull()
        expect(input()).toHaveValue('renew')
        expect(shown('text')).toEqual('renew')
        expect(shown('query')).toEqual('')
    })

    it('Esc closes the popover', async () => {
        const user = setup()
        await user.click(input())
        expect(listbox()).not.toBeNull()
        await user.keyboard('{Escape}')
        expect(listbox()).toBeNull()
    })

    it('Backspace on an empty input removes the last pill', async () => {
        const user = setup({
            filters: [
                { facet: 'status', value: 'draft', negated: false },
                { facet: 'status', value: 'archived', negated: true },
            ],
            text: '',
        })
        await user.click(input())
        await user.keyboard('{Backspace}')
        expect(shown('query')).toEqual('status:draft')
    })

    it('Tab on an empty input moves focus out of the bar', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('{Tab}')
        expect(document.querySelector('[data-attr="after"]')).toHaveFocus()
    })

    it('exposes the combobox and labels each pill remove button', async () => {
        const user = setup({ filters: [{ facet: 'status', value: 'draft', negated: true }], text: '' })
        expect(input()).toHaveAttribute('role', 'combobox')
        expect(input()).toHaveAttribute('aria-expanded', 'false')
        expect(document.querySelector('[aria-label="Remove filter Status is not: Draft"]')).not.toBeNull()

        await user.click(input())
        await user.keyboard('status:')
        expect(input()).toHaveAttribute('aria-expanded', 'true')
        expect(input().getAttribute('aria-controls')).toEqual(listbox()!.id)
        const selected = document.querySelector('[role="option"][aria-selected="true"]')!
        expect(input().getAttribute('aria-activedescendant')).toEqual(selected.id)
        expect(shown('facet-search-bar-hints')).toContain('Esc to close')
    })
})
