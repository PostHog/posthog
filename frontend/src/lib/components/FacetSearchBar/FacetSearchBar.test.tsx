import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { FacetDefinition, FacetSearchValue, serializeFacetQuery } from './facetQuery'
import { FacetSearchBar } from './FacetSearchBar'

interface Item {
    name: string
    status: string
    subjects: string[]
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
    { key: 'sends', label: 'Sends', description: 'Email subject', getValues: (item) => item.subjects },
]

const ITEMS: Item[] = [
    { name: 'Welcome', status: 'active', subjects: ['Your trial ends'] },
    { name: 'Renewal', status: 'draft', subjects: [] },
    { name: 'Promo', status: 'archived', subjects: [] },
]

function Harness({ initial }: { initial: FacetSearchValue }): JSX.Element {
    const [value, setValue] = useState(initial)
    return (
        <div>
            <button type="button" data-attr="before">
                Before
            </button>
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

    it.each([
        ['a typed facet value followed by a space', 'status:active ', 'status:active', ''],
        ['a closed quoted value', 'sends:"Your trial ends"', 'sends:"Your trial ends"', ''],
        ['text around a typed facet value', 'wel status:active ren', 'status:active', 'wel ren'],
    ])('turns %s into a pill', async (_, typed, query, text) => {
        const user = setup()
        await user.click(input())
        await user.keyboard(typed)
        expect(shown('query')).toEqual(query)
        expect(shown('text')).toEqual(text)
    })

    it('turns a pasted query into pills', async () => {
        const user = setup()
        await user.click(input())
        await user.paste('status:draft -status:archived ')
        expect(shown('query')).toEqual('status:draft -status:archived')
        expect(input()).toHaveValue('')
    })

    it('Shift+Tab moves focus back instead of applying a filter', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('sta')
        await user.keyboard('{Shift>}{Tab}{/Shift}')
        expect(document.querySelector('[data-attr="before"]')).toHaveFocus()
        expect(shown('query')).toEqual('')
    })

    it('Enter while an IME is composing does not apply the highlighted row', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('status:')
        fireEvent.keyDown(input(), { key: 'Enter', isComposing: true })
        expect(shown('query')).toEqual('')
        expect(input()).toHaveValue('status:')
    })

    it('keeps focus in the input when the popover chrome is pressed', async () => {
        const user = setup()
        await user.click(input())
        const hints = document.querySelector('[data-attr="facet-search-bar-hints"]')!
        // fireEvent returns false when the handler prevented the default, which is what keeps the focus.
        expect(fireEvent.mouseDown(hints)).toBe(false)
    })

    it('shows the no-values message as text, not as an option', async () => {
        const user = setup()
        await user.click(input())
        await user.keyboard('status:zzz')
        expect(document.querySelectorAll('[role="option"]')).toHaveLength(0)
        expect(listbox()).toHaveTextContent('No values match your other filters')
        expect(input()).not.toHaveAttribute('aria-activedescendant')
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
