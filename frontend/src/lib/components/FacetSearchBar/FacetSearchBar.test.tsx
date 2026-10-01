import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import {
    ClientFacet,
    FacetSearchRows,
    FacetValueOption,
    ServerFacet,
    filterFacetRows,
    parseFacetSearch,
    serializeFacetSearch,
    toFacetQuery,
} from './facetSearch'
import { FacetSearchBar } from './FacetSearchBar'

interface Row {
    name: string
    status: string
    subjects: string[]
}

const CLIENT_FACETS: ClientFacet<Row>[] = [
    {
        key: 'status',
        label: 'Status',
        description: 'Lifecycle',
        showOnFocus: true,
        order: 1,
        getValues: (row) => [row.status],
        formatValue: (value) => value[0].toUpperCase() + value.slice(1),
    },
    {
        key: 'sends',
        aliases: ['subject'],
        label: 'Sends',
        description: 'Email subject',
        showOnFocus: true,
        order: 2,
        getValues: (row) => row.subjects,
    },
    { key: 'stage', label: 'Stage', description: 'Found by typing', order: 3, getValues: () => ['one'] },
]

const DATA: FacetSearchRows<Row> = {
    rows: [
        { name: 'Welcome', status: 'active', subjects: ['Start here', 'Status update'] },
        { name: 'Renewal', status: 'draft', subjects: ['Renew now', 'Your trial ends'] },
        { name: 'Sync', status: 'draft', subjects: [] },
        { name: 'Promo', status: 'archived', subjects: ['Deals'] },
    ],
    matchesText: (row, text) => row.name.toLowerCase().includes(text.toLowerCase()),
}

function ClientConsumer({ url }: { url: string }): JSX.Element {
    const [value, setValue] = useState(() => parseFacetSearch(url, CLIENT_FACETS))
    return (
        <div>
            <button type="button" data-attr="before">
                Before
            </button>
            <FacetSearchBar
                facets={CLIENT_FACETS}
                data={DATA}
                value={value}
                onChange={setValue}
                placeholder="Search"
                dataAttr="client-search"
            />
            <output data-attr="url">{serializeFacetSearch(value)}</output>
            <output data-attr="rows">
                {filterFacetRows(DATA, value, CLIENT_FACETS)
                    .map((row) => row.name)
                    .join(',')}
            </output>
            <button type="button" data-attr="after">
                After
            </button>
        </div>
    )
}

function ServerConsumer({ facets }: { facets: ServerFacet[] }): JSX.Element {
    const [value, setValue] = useState({ filters: [], text: '' })
    return (
        <div>
            <FacetSearchBar
                facets={facets}
                value={value}
                onChange={setValue}
                placeholder="Search"
                dataAttr="server-search"
            />
            <output data-attr="query">{JSON.stringify(toFacetQuery(value))}</output>
        </div>
    )
}

const PLAN: ServerFacet = {
    key: 'plan',
    label: 'Plan',
    description: 'Billing plan',
    showOnFocus: true,
    values: [
        { value: 'free', label: 'Free' },
        { value: 'paid', label: 'Paid', count: 12 },
    ],
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve: (value: T) => void = () => {}
    const promise = new Promise<T>((done) => {
        resolve = done
    })
    return { promise, resolve }
}

const input = (): HTMLInputElement => document.querySelector<HTMLInputElement>('input[role="combobox"]')!
const shown = (attr: string): string => document.querySelector(`[data-attr="${attr}"]`)?.textContent ?? ''
const listbox = (): Element | null => document.querySelector('[role="listbox"]')
const pills = (): string[] =>
    [...document.querySelectorAll('[aria-label^="Remove filter "]')].map((button) =>
        button.getAttribute('aria-label')!.replace('Remove filter ', '')
    )

/** Each option as `label · detail (count)`, the way a user reads the row. */
const suggestions = (): string[] =>
    [...document.querySelectorAll('[role="option"]')].map((option) => {
        const leaves = [...option.querySelectorAll('span')].filter((span) => span.children.length === 0)
        const count = leaves.find((span) => span.getAttribute('translate') === 'no')?.textContent
        const [label, detail] = leaves
            .filter((span) => span.getAttribute('translate') !== 'no')
            .map((span) => span.textContent)
        return `${label}${detail ? ` · ${detail}` : ''}${count ? ` (${count})` : ''}`
    })

describe('FacetSearchBar', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    describe('client mode', () => {
        const setup = (url = ''): ReturnType<typeof userEvent.setup> => {
            render(<ClientConsumer url={url} />)
            return userEvent.setup()
        }

        it('lists the on-focus facets in order when the input is empty', async () => {
            const user = setup()
            await user.click(input())
            expect(suggestions()).toEqual(['status: · Lifecycle', 'sends: · Email subject'])
            expect(listbox()).toHaveAccessibleName('Filter by')
        })

        it('offers matching facets, then the search, then values from any facet with counts', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('sta')
            expect(suggestions()).toEqual([
                'status: · Lifecycle',
                'stage: · Found by typing',
                'Search for "sta"',
                'Sends: Start here (1)',
                'Sends: Status update (1)',
            ])
            expect(shown('rows')).toEqual('')
        })

        it.each([
            ['leave out the facet own pills', 'status:draft', 'status:', ['Active (1)', 'Archived (1)']],
            ['narrow down as the value is typed', 'status:draft', 'status:arch', ['Archived (1)']],
            ['count only rows the other facets let through', 'sends:Deals', 'status:', ['Archived (1)']],
        ])('value counts %s', async (_, url, typed, expected) => {
            const user = setup(url)
            await user.click(input())
            await user.keyboard(typed)
            expect(suggestions()).toEqual(expected)
        })

        it('offers "Not" values with how many rows they hide for a negated draft', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('-status:')
            expect(suggestions()).toEqual(['Not Draft · Hides 2', 'Not Active · Hides 1', 'Not Archived · Hides 1'])
            expect(listbox()).toHaveAccessibleName('Status is not')
        })

        it('filters rows with OR within a facet, AND across facets, and the text', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:draft status:archived ')
            expect(shown('rows')).toEqual('Renewal,Sync,Promo')
            await user.keyboard('-sends:Deals ')
            expect(shown('rows')).toEqual('Renewal,Sync')
            await user.keyboard('ren')
            expect(shown('rows')).toEqual('Renewal')
            expect(shown('url')).toEqual('status:draft status:archived -sends:Deals ren')
        })

        it('picks a value row with the keyboard and keeps the text typed before it', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('wel status:{ArrowDown}{Enter}')
            expect(pills()).toEqual(['Status: Active'])
            expect(input()).toHaveValue('wel ')
            expect(shown('rows')).toEqual('Welcome')
        })

        it('Tab and → take the first filter row, never the search row', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('sta{ArrowDown}{ArrowDown}')
            expect(document.querySelector('[role="option"][aria-selected="true"]')).toHaveTextContent(
                'Search for "sta"'
            )
            expect(shown('facet-search-bar-hints')).toContain('Tab or → to pick status:')

            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('status:')

            await user.keyboard('act{ArrowRight}')
            expect(pills()).toEqual(['Status: Active'])
            expect(input()).toHaveValue('')
            expect(input()).toHaveFocus()
        })

        it('Enter on the search row closes the popover and keeps the text', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('renew{Enter}')
            expect(listbox()).toBeNull()
            expect(input()).toHaveValue('renew')
            expect(shown('rows')).toEqual('Renewal')
        })

        it('Esc closes the popover', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('{Escape}')
            expect(listbox()).toBeNull()
        })

        it('removes the last pill with Backspace on an empty input, and any pill with its remove button', async () => {
            const user = setup('status:draft -status:archived sends:Deals')
            expect(pills()).toEqual(['Status: Draft', 'Status is not: Archived', 'Sends: Deals'])
            await user.click(input())
            await user.keyboard('{Backspace}')
            expect(shown('url')).toEqual('status:draft -status:archived')

            await user.click(document.querySelector('[aria-label="Remove filter Status: Draft"]')!)
            expect(shown('url')).toEqual('-status:archived')
        })

        it('moves focus with Tab on an empty input and with Shift+Tab', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('{Tab}')
            expect(document.querySelector('[data-attr="after"]')).toHaveFocus()

            await user.click(input())
            await user.keyboard('sta{Shift>}{Tab}{/Shift}')
            expect(document.querySelector('[data-attr="before"]')).toHaveFocus()
            expect(pills()).toEqual([])
        })

        it.each([
            ['a typed facet value followed by a space', 'status:active ', 'status:active'],
            ['a closed quoted value', 'sends:"Your trial ends"', 'sends:"Your trial ends"'],
            ['text around a typed facet value', 'wel status:active ren', 'status:active wel ren'],
            ['a facet alias', 'subject:Deals ', 'sends:Deals'],
            ['an unknown facet, which stays text', 'owner:me ', 'owner:me'],
        ])('turns %s into pills and text', async (_, typed, url) => {
            const user = setup()
            await user.click(input())
            await user.keyboard(typed)
            expect(shown('url')).toEqual(url)
        })

        it('turns a pasted query into pills, each once', async () => {
            const user = setup()
            await user.click(input())
            await user.paste('status:draft -status:archived status:draft ')
            expect(pills()).toEqual(['Status: Draft', 'Status is not: Archived'])
            expect(input()).toHaveValue('')
        })

        it('ignores Enter while an IME is composing', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:')
            fireEvent.keyDown(input(), { key: 'Enter', isComposing: true })
            expect(pills()).toEqual([])
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
            expect(suggestions()).toEqual([])
            expect(listbox()).toHaveTextContent('No values match your other filters')
            expect(input()).not.toHaveAttribute('aria-activedescendant')
            expect(shown('facet-search-bar-hints')).toEqual('↑↓ to moveEsc to close')
        })

        it('exposes the combobox and points it at the highlighted option', async () => {
            const user = setup('-status:draft')
            expect(input()).toHaveAttribute('aria-expanded', 'false')

            await user.click(input())
            await user.keyboard('status:')
            expect(input()).toHaveAttribute('aria-expanded', 'true')
            expect(input().getAttribute('aria-controls')).toEqual(listbox()!.id)
            const selected = document.querySelector('[role="option"][aria-selected="true"]')!
            expect(input().getAttribute('aria-activedescendant')).toEqual(selected.id)
        })
    })

    describe('server mode', () => {
        it('suggests supplied values in order with counts only where given, and builds the query', async () => {
            render(<ServerConsumer facets={[PLAN]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('plan:')
            expect(suggestions()).toEqual(['Free', 'Paid (12)'])

            await user.keyboard('{Enter}-plan:pa{Enter}acme')
            expect(pills()).toEqual(['Plan: Free', 'Plan is not: Paid'])
            expect(JSON.parse(shown('query'))).toEqual({
                text: 'acme',
                facets: { plan: { include: ['free'], exclude: ['paid'] } },
            })
        })

        it('loads values for what was typed after the colon, and labels the pill from them', async () => {
            const teams = deferred<FacetValueOption[]>()
            const loadValues = jest.fn((_search: string) => teams.promise)
            render(<ServerConsumer facets={[PLAN, { key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:plat')
            expect(listbox()).toHaveTextContent('Loading values…')
            await waitFor(() => expect(loadValues).toHaveBeenCalledWith('plat'))

            teams.resolve([{ value: 't-2', label: 'Platform' }])
            await waitFor(() => expect(suggestions()).toEqual(['Platform']))
            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Team: Platform'])
            expect(JSON.parse(shown('query')).facets).toEqual({ team: { include: ['t-2'], exclude: [] } })
        })

        it('offers loaded values from a word typed without a facet', async () => {
            const loadValues = async (): Promise<FacetValueOption[]> => [{ value: 't-1', label: 'Growth' }]
            render(<ServerConsumer facets={[PLAN, { key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('gro')
            await waitFor(() => expect(suggestions()).toEqual(['Search for "gro"', 'Team: Growth']))
        })

        it('says when loading values failed, and loads again on the next keystroke', async () => {
            const loadValues = jest
                .fn<Promise<FacetValueOption[]>, [string]>()
                .mockRejectedValueOnce(new Error('offline'))
                .mockResolvedValue([{ value: 't-1', label: 'Growth' }])
            render(<ServerConsumer facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(listbox()).toHaveTextContent("Couldn't load values. Type again to retry."))

            await user.keyboard('g')
            await waitFor(() => expect(suggestions()).toEqual(['Growth']))
        })
    })
})
