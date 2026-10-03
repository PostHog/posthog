import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, isInaccessible, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import {
    ClientFacet,
    FacetSearchRows,
    FacetValueOption,
    LoadFacetValues,
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
        formatValue: (value) => value.charAt(0).toUpperCase() + value.slice(1),
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

const NO_SUBJECTS: FacetSearchRows<Row> = { ...DATA, rows: DATA.rows.map((row) => ({ ...row, subjects: [] })) }

function ClientConsumer({ url, data = DATA }: { url: string; data?: FacetSearchRows<Row> }): JSX.Element {
    const [value, setValue] = useState(() => parseFacetSearch(url, CLIENT_FACETS))
    return (
        <div>
            <button type="button" data-attr="before">
                Before
            </button>
            <FacetSearchBar
                facets={CLIENT_FACETS}
                data={data}
                value={value}
                onChange={setValue}
                placeholder="Search"
                dataAttr="client-search"
            />
            <output data-attr="url">{serializeFacetSearch(value)}</output>
            <output data-attr="rows">
                {filterFacetRows(data, value, CLIENT_FACETS)
                    .map((row) => row.name)
                    .join(',')}
            </output>
            <button type="button" data-attr="after">
                After
            </button>
        </div>
    )
}

function UrlBackedClientConsumer(): JSX.Element {
    const [url, setUrl] = useState('')
    return (
        <FacetSearchBar
            facets={CLIENT_FACETS}
            data={DATA}
            value={parseFacetSearch(url, CLIENT_FACETS)}
            onChange={(value) => setUrl(serializeFacetSearch(value))}
            placeholder="Search"
            dataAttr="url-search"
        />
    )
}

function ServerConsumer({ facets, url = '' }: { facets: ServerFacet[]; url?: string }): JSX.Element {
    const [value, setValue] = useState(() => parseFacetSearch(url, facets))
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
            <output data-attr="url">{serializeFacetSearch(value)}</output>
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
        { value: 'paid', label: 'Paid', count: 1204 },
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
const option = (startingWith: string): Element =>
    [...document.querySelectorAll('[role="option"]')].find((element) => element.textContent?.startsWith(startingWith))!
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
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

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
            [
                'leave out a value the facet already excludes',
                '-status:archived',
                'status:',
                ['Draft (2)', 'Active (1)'],
            ],
            [
                'of a negated value count only rows the facet still lets through',
                'status:draft',
                '-status:',
                ['Not Draft · Hides 2'],
            ],
        ])('value counts %s', async (_, url, typed, expected) => {
            const user = setup(url)
            await user.click(input())
            await user.keyboard(typed)
            expect(suggestions()).toEqual(expected)
        })

        it('stops offering a value once a pill holds it in any case', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:Draft status:draft status:')
            expect(pills()).toEqual(['Status: Draft'])
            expect(shown('rows')).toEqual('Renewal,Sync')
            expect(suggestions()).toEqual(['Active (1)', 'Archived (1)'])
        })

        it.each([
            ['a closed quote', 'sends:"See status:open now" ', ['Sends: See status:open now']],
            ['a quote that ends in an escape', 'sends:"See status:open C:\\', []],
        ])('keeps a facet token typed inside %s as part of the quoted value', async (_, typed, expected) => {
            const user = setup()
            await user.click(input())
            await user.keyboard(typed)
            expect(pills()).toEqual(expected)
        })

        it('counts the rows a negated value hides when it is typed without a facet', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('-dea')
            expect(suggestions()).toContain('Not Sends: Deals · Hides 1')
        })

        it('keeps the popover and Tab target when the person presses the bar around the text', async () => {
            const user = setup('status:draft')
            await user.click(input())
            await user.keyboard('sta')
            await user.click(document.querySelector('.LemonInput')!)
            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('status:')
        })

        it('scrolls the highlighted option into view for the keyboard, not for the pointer', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:')
            const scrollIntoView = jest.fn()
            for (const option of document.querySelectorAll<HTMLElement>('[role="option"]')) {
                option.scrollIntoView = scrollIntoView
            }

            await user.keyboard('{ArrowUp}')
            await user.hover(document.querySelectorAll('[role="option"]')[2])
            expect(scrollIntoView).not.toHaveBeenCalled()

            await user.keyboard('{ArrowUp}')
            expect(scrollIntoView).toHaveBeenCalled()
        })

        it('highlights the option under the pointer, so Enter picks it', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:')
            await user.hover(document.querySelectorAll('[role="option"]')[1])
            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Status: Active'])
        })

        it('keeps the keyboard highlight when a row scrolls under a pointer that does not move', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:{ArrowDown}')
            fireEvent.mouseOver(document.querySelectorAll('[role="option"]')[2])
            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Status: Active'])
        })

        it('picks a facet and then a value with the pointer', async () => {
            const user = setup()
            await user.click(input())
            await user.click(option('status:'))
            expect(input()).toHaveValue('status:')

            await user.click(option('Active'))
            expect(pills()).toEqual(['Status: Active'])
            expect(shown('url')).toEqual('status:active')
            expect(input()).toHaveFocus()
        })

        it('keeps Tab picking a filter after a click inside the open input', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('sta')
            await user.click(input())
            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('status:')
        })

        it('lets Enter submit a surrounding form while the popover is closed', async () => {
            const onSubmit = jest.fn((event: React.FormEvent) => event.preventDefault())
            render(
                <form onSubmit={onSubmit}>
                    <ClientConsumer url="" />
                </form>
            )
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('renew{Enter}')
            expect(onSubmit).not.toHaveBeenCalled()

            await user.keyboard('{Enter}')
            expect(onSubmit).toHaveBeenCalledTimes(1)
        })

        it('recounts open suggestions when the rows change', async () => {
            const { rerender } = render(<ClientConsumer url="" />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('status:{ArrowDown}')
            expect(suggestions()).toEqual(['Draft (2)', 'Active (1)', 'Archived (1)'])

            const moreRows = { ...DATA, rows: [...DATA.rows, { name: 'Launch', status: 'active', subjects: [] }] }
            rerender(<ClientConsumer url="" data={moreRows} />)
            expect(suggestions()).toEqual(['Active (2)', 'Draft (2)', 'Archived (1)'])

            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Status: Active'])
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
            await user.keyboard('sends:Deals ')
            expect(shown('rows')).toEqual('Promo')
            await user.keyboard('{Backspace}-sends:"Your trial ends" ')
            expect(shown('rows')).toEqual('Sync,Promo')
            await user.keyboard('syn')
            expect(shown('rows')).toEqual('Sync')
            expect(shown('url')).toEqual('status:draft status:archived -sends:"Your trial ends" syn')
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
            await user.keyboard('sta')
            expect(document.querySelector('[role="option"][aria-selected="true"]')).toHaveTextContent(
                'Search for "sta"'
            )
            expect(shown('client-search-hints')).toContain('⇥→to pick status:')

            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('status:')

            await user.keyboard('act{ArrowRight}')
            expect(pills()).toEqual(['Status: Active'])
            expect(input()).toHaveValue('')
            expect(input()).toHaveFocus()
        })

        it.each([
            ['a word that is no facet name', 'renew', 'Renewal'],
            ['a word that starts a facet name', 'sta', ''],
            ['a word followed by a space', 'renew ', 'Renewal'],
        ])('Enter runs the search for %s and keeps the text', async (_, typed, rows) => {
            const user = setup()
            await user.click(input())
            await user.keyboard(`${typed}{Enter}`)
            expect(listbox()).toBeNull()
            expect(input()).toHaveValue(typed)
            expect(shown('url')).toEqual(typed.trim())
            expect(shown('rows')).toEqual(rows)
        })

        it('offers only the search inside an open quoted phrase', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('"See sta')
            expect(suggestions()).toEqual(['Search for ""See sta"'])

            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('"See sta')
            expect(shown('url')).toEqual('"See sta')
        })

        it('puts a value that equals the typed text before values that only contain it', async () => {
            const withInactive = {
                ...DATA,
                rows: [
                    ...DATA.rows,
                    { name: 'Old', status: 'inactive', subjects: [] },
                    { name: 'Older', status: 'inactive', subjects: [] },
                ],
            }
            render(<ClientConsumer url="" data={withInactive} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('status:active')
            expect(suggestions()).toEqual(['Active (1)', 'Inactive (2)'])

            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Status: Active'])
        })

        it('lists the on-focus facets as exclusions when the person types a minus', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('-')
            expect(suggestions()).toEqual(['-status: · Lifecycle', '-sends: · Email subject', 'Search for "-"'])

            await user.keyboard('{Tab}')
            expect(input()).toHaveValue('-status:')
        })

        it('leaves ArrowUp to the input while the popover is closed', async () => {
            const user = setup()
            await user.click(input())
            await user.keyboard('renew{Escape}')
            expect(fireEvent.keyDown(input(), { key: 'ArrowUp' })).toBe(true)
        })

        it.each([
            ['its own text', 'sends:"Start here\\'],
            ['a facet token inside it', 'sends:"See status:op\\'],
        ])('keeps an open quoted draft that ends in an escape, with %s, out of the search text', async (_, typed) => {
            const user = setup()
            await user.click(input())
            await user.keyboard(typed)
            expect(shown('url')).toEqual('')
        })

        describe('when the consumer changes the search', () => {
            function ResettableConsumer({ url, replacement }: { url: string; replacement: string }): JSX.Element {
                const [value, setValue] = useState(() => parseFacetSearch(url, CLIENT_FACETS))
                return (
                    <div>
                        <FacetSearchBar
                            facets={CLIENT_FACETS}
                            data={DATA}
                            value={value}
                            onChange={setValue}
                            placeholder="Search"
                            dataAttr="resettable-search"
                        />
                        <button type="button" data-attr="clear" onClick={() => setValue({ filters: [], text: '' })}>
                            Clear
                        </button>
                        <button
                            type="button"
                            data-attr="replace"
                            onClick={() => setValue(parseFacetSearch(replacement, CLIENT_FACETS))}
                        >
                            Replace
                        </button>
                        <output data-attr="url">{serializeFacetSearch(value)}</output>
                    </div>
                )
            }
            const setupResettable = (url: string, replacement = ''): ReturnType<typeof userEvent.setup> => {
                render(<ResettableConsumer url={url} replacement={replacement} />)
                return userEvent.setup()
            }
            const press = (attr: string): HTMLElement => document.querySelector<HTMLElement>(`[data-attr="${attr}"]`)!

            it('drops a typed draft when the search is cleared', async () => {
                const user = setupResettable('status:draft')
                await user.click(input())
                await user.keyboard('status:act')
                await user.click(press('clear'))
                expect(pills()).toEqual([])
                expect(input()).toHaveValue('')
            })

            it('drops a typed draft when the search is set back to one the bar sent before', async () => {
                const user = setupResettable('', 'status:draft')
                await user.click(input())
                await user.keyboard('status:draft ')
                await user.click(press('clear'))
                await user.click(input())
                await user.paste('status:act')
                await user.click(press('replace'))
                expect(shown('url')).toEqual('status:draft')
                expect(input()).toHaveValue('')
            })

            it('drops a typed draft when only the spaces inside a quoted pill value change', async () => {
                const user = setupResettable('sends:"Your trial ends"', 'sends:"Your  trial ends"')
                await user.click(input())
                await user.keyboard('status:act')
                await user.click(press('replace'))
                expect(shown('url')).toEqual('sends:"Your  trial ends"')
                expect(input()).toHaveValue('')
            })
        })

        it('Esc closes the popover before anything around the bar, and a click on the input opens it again', async () => {
            const onParentEscape = jest.fn()
            render(
                <div onKeyDown={(event) => event.key === 'Escape' && onParentEscape()}>
                    <ClientConsumer url="" />
                </div>
            )
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('{Escape}')
            expect(listbox()).toBeNull()
            expect(onParentEscape).not.toHaveBeenCalled()

            await user.keyboard('{Escape}')
            expect(onParentEscape).toHaveBeenCalledTimes(1)

            await user.click(input())
            expect(listbox()).not.toBeNull()
        })

        it('removes the last pill with Backspace on an empty input, and any pill with its remove button', async () => {
            const user = setup('status:draft -status:archived sends:Deals')
            expect(pills()).toEqual(['Status: Draft', 'Status is not: Archived', 'Sends: Deals'])
            await user.click(input())
            await user.keyboard('{Backspace}')
            expect(shown('url')).toEqual('status:draft -status:archived')

            await user.click(document.querySelector('[aria-label="Remove filter Status: Draft"]')!)
            expect(shown('url')).toEqual('-status:archived')
            expect(input()).toHaveFocus()
        })

        it('removes a pill with the pointer without opening the suggestions over the results', async () => {
            const user = setup('status:draft sends:Deals')
            await user.click(document.querySelector('[aria-label="Remove filter Status: Draft"]')!)
            expect(shown('url')).toEqual('sends:Deals')
            expect(listbox()).toBeNull()
            expect(input()).not.toHaveFocus()

            document.querySelector<HTMLElement>('[aria-label="Remove filter Sends: Deals"]')!.focus()
            await user.keyboard('{Enter}')
            expect(shown('url')).toEqual('')
            expect(input()).toHaveFocus()
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

        it('lets Tab pass through a search restored from the URL without adding a pill', async () => {
            const user = setup('ren')
            await user.click(document.querySelector('[data-attr="before"]')!)
            await user.keyboard('{Tab}')
            expect(input()).toHaveFocus()

            await user.keyboard('{Tab}')
            expect(document.querySelector('[data-attr="after"]')).toHaveFocus()
            expect(pills()).toEqual([])
        })

        it('keeps the spaces typed in the text when the consumer stores the search as a URL', async () => {
            render(<UrlBackedClientConsumer />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('renew  now')
            expect(input()).toHaveValue('renew  now')
        })

        it.each([
            [
                'a typed facet value followed by a space',
                'status:active ',
                'status:active',
                ['Status: Active'],
                'Welcome',
            ],
            [
                'a closed quoted value',
                'sends:"Your trial ends"',
                'sends:"Your trial ends"',
                ['Sends: Your trial ends'],
                'Renewal',
            ],
            [
                'text around a typed facet value',
                'wel status:active ren',
                'status:active wel ren',
                ['Status: Active'],
                '',
            ],
            ['a facet alias', 'subject:Deals ', 'sends:Deals', ['Sends: Deals'], 'Promo'],
            ['an unknown facet, which stays text', 'owner:me ', 'owner:me', [], ''],
            ['a facet value glued to a closing quote', '"See status:open"', '"See status:open"', [], ''],
            ['a quoted phrase that holds a facet token', '"See status:open now" ', '"See status:open now"', [], ''],
            ['an open quoted phrase that holds a facet token', '"See status:op', '"See status:op', [], ''],
            ['a quoted phrase, matched without its quotes', '"renew"', '"renew"', [], 'Renewal'],
        ])('turns %s into pills and text', async (_, typed, url, expectedPills, expectedRows) => {
            const user = setup()
            await user.click(input())
            await user.keyboard(typed)
            expect(shown('url')).toEqual(url)
            expect(pills()).toEqual(expectedPills)
            expect(shown('rows')).toEqual(expectedRows)
        })

        it.each([
            ['a value with spaces', { facet: 'sends', value: 'Your trial ends', negated: false }],
            ['a value with quotes and backslashes', { facet: 'sends', value: 'Say "hi" C:\\temp\\', negated: true }],
            ['an empty value', { facet: 'sends', value: '', negated: false }],
            ['a value ending in a colon', { facet: 'sends', value: 'Meeting notes:', negated: false }],
        ])('restores %s from the URL', (_, filter) => {
            const search = { filters: [filter], text: 'renew' }
            expect(parseFacetSearch(serializeFacetSearch(search), CLIENT_FACETS)).toEqual(search)
        })

        it.each([
            [
                'an escaped line break inside a quoted value',
                'sends:"Say \\\nstatus:open now"',
                { filters: [{ facet: 'sends', value: 'Say \nstatus:open now', negated: false }], text: '' },
            ],
            [
                'a quoted phrase',
                '"See status:open now" -status:draft',
                {
                    filters: [{ facet: 'status', value: 'draft', negated: true }],
                    text: '"See status:open now"',
                },
            ],
            [
                'a quoted value it is glued to',
                'status:"open"status:closed',
                { filters: [], text: 'status:"open"status:closed' },
            ],
        ])('keeps a facet token after %s in a URL as part of it', (_, url, expected) => {
            const parsed = parseFacetSearch(url, CLIENT_FACETS)
            expect(parsed).toEqual(expected)
            expect(parseFacetSearch(serializeFacetSearch(parsed), CLIENT_FACETS)).toEqual(parsed)
        })

        it('turns a pasted query into pills, each once', async () => {
            const user = setup()
            await user.click(input())
            await user.paste('status:draft -status:archived status:draft ')
            expect(pills()).toEqual(['Status: Draft', 'Status is not: Archived'])
            expect(input()).toHaveValue('')
        })

        it('adds a pasted filter next to pills from the URL that differ only by case', async () => {
            const user = setup('status:Draft status:draft')
            await user.click(input())
            await user.paste('sends:"Your trial ends" ')
            expect(shown('url')).toEqual('status:Draft status:draft sends:"Your trial ends"')
            expect(shown('rows')).toEqual('Renewal')
            expect(input()).toHaveValue('')
        })

        it.each([
            ['while it composes', { isComposing: true }],
            ['that confirms the text in Safari', { keyCode: 229 }],
        ])('ignores the IME Enter %s', async (_, composition) => {
            const user = setup()
            await user.click(input())
            await user.keyboard('status:')
            fireEvent.keyDown(input(), { key: 'Enter', ...composition })
            expect(pills()).toEqual([])
            expect(input()).toHaveValue('status:')
        })

        it('leaves text an IME is still composing alone, and reads it once composition ends', async () => {
            const { rerender } = render(<ClientConsumer url="" />)
            const user = userEvent.setup()
            await user.click(input())
            fireEvent.compositionStart(input())
            fireEvent.change(input(), { target: { value: 'sends:ni hao' } })
            expect(pills()).toEqual([])
            expect(input()).toHaveValue('sends:ni hao')

            rerender(<ClientConsumer url="" data={{ ...DATA }} />)
            expect(input()).toHaveValue('sends:ni hao')

            fireEvent.change(input(), { target: { value: 'sends:Deals ' } })
            fireEvent.compositionEnd(input())
            expect(pills()).toEqual(['Sends: Deals'])
            expect(input()).toHaveValue('')
        })

        it('keeps the suggestions closed when composition ends after the input lost focus', async () => {
            const user = setup()
            await user.click(input())
            fireEvent.compositionStart(input())
            fireEvent.change(input(), { target: { value: 'renew' } })
            fireEvent.blur(input())
            fireEvent.compositionEnd(input())
            expect(document.querySelector('[data-attr="client-search-hints"]')).toBeNull()
            expect(shown('url')).toEqual('renew')
        })

        it('keeps focus in the input when the popover chrome is pressed', async () => {
            const user = setup()
            await user.click(input())
            await user.click(document.querySelector('[data-attr="client-search-hints"]')!)
            expect(input()).toHaveFocus()
            expect(listbox()).not.toBeNull()
        })

        it.each([
            ['the typed value', '', DATA, 'status:zzz', 'No values match'],
            ['the other filters', '', DATA, 'zzz status:', 'No values match your other filters'],
            ['a facet no row has a value for', 'sends:Old', NO_SUBJECTS, 'sends:', 'This filter has no values'],
            ['a facet whose every value is a pill', 'stage:one', DATA, 'stage:', 'Every value is already a filter'],
            [
                'a typed value that only matches pills',
                'status:draft',
                DATA,
                'status:dra',
                'Every matching value is already a filter',
            ],
        ])('shows the no-values message for %s as text, not as an option', async (_, url, data, typed, expected) => {
            render(<ClientConsumer url={url} data={data} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard(typed)
            expect(suggestions()).toEqual([])
            expect(listbox()).toBeNull()
            expect(document.querySelector('[role="status"]')).toHaveTextContent(new RegExp(`^${expected}$`))
            expect(screen.getAllByText(expected).filter((element) => !isInaccessible(element))).toHaveLength(1)
            expect(input()).toHaveAttribute('aria-expanded', 'false')
            expect(input()).not.toHaveAttribute('aria-activedescendant')
            expect(shown('client-search-hints')).toEqual('escto close')
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

        it('shows an empty value as an empty string in suggestions and pills', async () => {
            const withEmptySubject = {
                ...DATA,
                rows: DATA.rows.map((row) => ({ ...row, subjects: row.subjects.length ? row.subjects : [''] })),
            }
            render(<ClientConsumer url="" data={withEmptySubject} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('sends:st')
            expect(suggestions()).toEqual(['Start here (1)', 'Status update (1)'])

            await user.keyboard('{Backspace}{Backspace}')
            expect(suggestions()[0]).toEqual('(empty string) (1)')
            await user.keyboard('{Enter}')
            expect(pills()).toEqual(['Sends: (empty string)'])
            expect(shown('url')).toEqual('sends:""')
            expect(shown('rows')).toEqual('Sync')
        })
    })

    describe('server mode', () => {
        it('suggests supplied values in order with counts only where given, and builds the query', async () => {
            render(<ServerConsumer facets={[PLAN]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('plan:')
            expect(suggestions()).toEqual(['Free', 'Paid (1,204)'])

            await user.keyboard('{Enter}-plan:')
            expect(suggestions()).toEqual(['Not Free', 'Not Paid (1,204)'])

            await user.keyboard('pa{Enter}acme')
            expect(pills()).toEqual(['Plan: Free', 'Plan is not: Paid'])
            expect(JSON.parse(shown('query'))).toEqual({
                text: 'acme',
                facets: { plan: { include: ['free'], exclude: ['paid'] } },
            })
        })

        it('builds one query group per facet with every included and excluded value', () => {
            const search = parseFacetSearch('plan:free plan:paid -team:t-1 team:t-2 -team:t-3 "acme corp"', [
                PLAN,
                { key: 'team', label: 'Team', description: 'Owner', values: [] },
            ])
            expect(toFacetQuery(search)).toEqual({
                text: 'acme corp',
                facets: {
                    plan: { include: ['free', 'paid'], exclude: [] },
                    team: { include: ['t-2'], exclude: ['t-1', 't-3'] },
                },
            })
        })

        it('keeps the popover closed until there is something to suggest', async () => {
            render(<ServerConsumer facets={[{ ...PLAN, showOnFocus: false }]} />)
            const user = userEvent.setup()
            await user.click(input())
            expect(input()).toHaveAttribute('aria-expanded', 'false')
            expect(shown('server-search-hints')).toEqual('')

            await user.keyboard('pl')
            expect(input()).toHaveAttribute('aria-expanded', 'true')
            expect(suggestions()).toEqual(['plan: · Billing plan', 'Search for "pl"'])
        })

        it('loads values for what was typed after the colon, and labels the pill from them', async () => {
            const teams = deferred<FacetValueOption[]>()
            const loadValues = jest.fn((_search: string) => teams.promise)
            render(<ServerConsumer facets={[PLAN, { key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:plat')
            expect(document.querySelector('[role="status"]')).toHaveTextContent('Loading values…')
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

        it('says when values for a word typed without a facet are loading or failed, next to the search row', async () => {
            const teams = deferred<FacetValueOption[]>()
            const loadValues = jest
                .fn<Promise<FacetValueOption[]>, [string]>()
                .mockReturnValueOnce(teams.promise)
                .mockRejectedValue(new Error('You are offline.'))
            render(<ServerConsumer facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const status = document.querySelector('[role="status"]')
            expect(status).toBeEmptyDOMElement()
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('gr')
            await waitFor(() => expect(loadValues).toHaveBeenCalledWith('gr'))
            expect(status).toHaveTextContent('Loading values…')
            expect(suggestions()).toEqual(['Search for "gr"'])

            await user.paste('o')
            await waitFor(() =>
                expect(status).toHaveTextContent("Couldn't load values for Team: You are offline. Type again to retry.")
            )
            expect(document.querySelector('[role="status"]')).toBe(status)
            expect(suggestions()).toEqual(['Search for "gro"'])
        })

        it('says when loading values failed, and loads again on the next keystroke', async () => {
            const loadValues = jest
                .fn<Promise<FacetValueOption[]>, [string]>()
                .mockRejectedValueOnce(new Error('You are offline.'))
                .mockResolvedValue([{ value: 't-1', label: 'Growth' }])
            render(<ServerConsumer facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() =>
                expect(document.querySelector('[role="status"]')).toHaveTextContent(
                    "Couldn't load values: You are offline. Type again to retry."
                )
            )

            await user.keyboard('g{Backspace}')
            await waitFor(() => expect(suggestions()).toEqual(['Growth']))
            expect(loadValues.mock.calls.filter(([search]) => search === '')).toHaveLength(2)
        })

        it('retries a failed load on the next keystroke, not on every render of the consumer', async () => {
            const loadValues = jest.fn(async (): Promise<FacetValueOption[]> => {
                throw new Error('Server error')
            })
            const facets: ServerFacet[] = [{ key: 'team', label: 'Team', description: 'Owner', loadValues }]
            const bar = (): JSX.Element => (
                <FacetSearchBar
                    facets={facets}
                    value={parseFacetSearch('team:t-2', facets)}
                    onChange={() => {}}
                    placeholder="Search"
                    dataAttr="url-backed-search"
                />
            )
            const { rerender } = render(bar())
            await waitFor(() => expect(loadValues).toHaveBeenCalledTimes(1))

            rerender(bar())
            rerender(bar())
            await act(async () => {
                await new Promise((resolve) => setTimeout(resolve, 0))
            })
            expect(loadValues).toHaveBeenCalledTimes(1)
        })

        it('loads values for a search restored from the URL as soon as the bar opens', async () => {
            const loadValues = jest.fn(async (): Promise<FacetValueOption[]> => [{ value: 't-1', label: 'Growth' }])
            render(
                <ServerConsumer url="gro" facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]} />
            )
            const user = userEvent.setup()
            await user.click(input())
            await waitFor(() => expect(suggestions()).toEqual(['Search for "gro"', 'Team: Growth']))
        })

        it('marks a restored pill whose label could not load, and keeps it marked while unrelated text is typed', async () => {
            const loadValues = jest
                .fn<Promise<FacetValueOption[]>, [string]>()
                .mockRejectedValue(new Error('Forbidden'))
            render(
                <ServerConsumer
                    url="-team:t-2"
                    facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]}
                />
            )
            const note = "Team is not: t-2 (couldn't load the label: Forbidden)"
            const pill = (): Element => document.querySelector('[data-attr="server-search-filter"]')!
            await waitFor(() => expect(pill()).toHaveTextContent(note))
            expect(screen.getByTitle(note)).toBeInTheDocument()
            expect(pills()).toEqual(['Team is not: t-2'])

            const user = userEvent.setup()
            await user.click(input())
            await user.paste('acme')
            await waitFor(() => expect(loadValues).toHaveBeenCalledWith('acme'))
            expect(loadValues.mock.calls.filter(([search]) => search === '')).toHaveLength(1)
            expect(pill()).toHaveTextContent(note)
        })

        it('leaves out the retry hint when the error says access is missing', async () => {
            const loadValues = async (): Promise<FacetValueOption[]> => {
                throw Object.assign(new Error('You do not have access to teams.'), { status: 403 })
            }
            render(<ServerConsumer facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues }]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() =>
                expect(document.querySelector('[role="status"]')).toHaveTextContent(
                    /^Couldn't load values: You do not have access to teams\.$/
                )
            )
        })

        it('marks a restored pill while its label loads, then labels it', async () => {
            const teams = deferred<FacetValueOption[]>()
            render(
                <ServerConsumer
                    url="-team:t-2"
                    facets={[{ key: 'team', label: 'Team', description: 'Owner', loadValues: () => teams.promise }]}
                />
            )
            const pill = (): Element => document.querySelector('[data-attr="server-search-filter"]')!
            const note = 'Team is not: t-2 (loading the label)'
            expect(pill()).toHaveTextContent(note)
            expect(screen.getByTitle(note)).toBeInTheDocument()
            expect(pill().querySelector('.Spinner')).not.toBeNull()

            teams.resolve([{ value: 't-2', label: 'Platform' }])
            await waitFor(() => expect(pills()).toEqual(['Team is not: Platform']))
            expect(pill()).toHaveTextContent(/^Team is not: Platform$/)
            expect(pill().querySelector('.Spinner')).toBeNull()
        })

        it('drops values from a replaced loader, including a load still in flight', async () => {
            const oldTeams = deferred<FacetValueOption[]>()
            const teamFacet = (loadValues: LoadFacetValues): ServerFacet[] => [
                { key: 'team', label: 'Team', description: 'Owner', loadValues },
            ]
            const { rerender } = render(<ServerConsumer facets={teamFacet(() => oldTeams.promise)} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(document.querySelector('[role="status"]')).toHaveTextContent('Loading values…'))

            rerender(<ServerConsumer facets={teamFacet(async () => [{ value: 'new', label: 'New project team' }])} />)
            oldTeams.resolve([{ value: 'old', label: 'Old project team' }])
            await waitFor(() => expect(suggestions()).toEqual(['New project team']))
        })

        it.each([
            [
                'after the new load',
                async (finishOldLoad: () => Promise<void>): Promise<void> => {
                    await waitFor(() => expect(suggestions()).toEqual(['New project team']))
                    await finishOldLoad()
                },
            ],
            [
                'before the new load starts',
                async (finishOldLoad: () => Promise<void>): Promise<void> => finishOldLoad(),
            ],
        ])("keeps the newest load when a returning loader's older load finishes %s", async (_, settle) => {
            const oldTeams = deferred<FacetValueOption[]>()
            const loadTeams = jest
                .fn<Promise<FacetValueOption[]>, [string]>()
                .mockReturnValueOnce(oldTeams.promise)
                .mockResolvedValue([{ value: 'new', label: 'New project team' }])
            const teamFacet = (loadValues: LoadFacetValues): ServerFacet[] => [
                { key: 'team', label: 'Team', description: 'Owner', loadValues },
            ]
            const { rerender } = render(<ServerConsumer facets={teamFacet(loadTeams)} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(loadTeams).toHaveBeenCalledTimes(1))

            rerender(<ServerConsumer facets={teamFacet(async () => [])} />)
            rerender(<ServerConsumer facets={teamFacet(loadTeams)} />)
            await settle(async () => {
                await act(async () => {
                    oldTeams.resolve([{ value: 'old', label: 'Old project team' }])
                    await oldTeams.promise
                })
            })
            await waitFor(() => expect(suggestions()).toEqual(['New project team']))
        })

        const repeatedValues: FacetValueOption[] = [
            { value: 'a', label: 'Alpha' },
            { value: 'a', label: 'Alpha' },
            { value: 'b', label: 'Beta' },
        ]
        it.each<[string, ServerFacet]>([
            ['loaded', { key: 'team', label: 'Team', description: 'Owner', loadValues: async () => repeatedValues }],
            ['supplied', { key: 'team', label: 'Team', description: 'Owner', values: repeatedValues }],
        ])('shows each %s value once', async (_, facet) => {
            render(<ServerConsumer facets={[facet]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(suggestions()).toEqual(['Alpha', 'Beta']))
        })

        it('loads values again for a facet that comes back while its last load was in flight', async () => {
            const oldTeams = deferred<FacetValueOption[]>()
            const teamFacet = (loadValues: LoadFacetValues): ServerFacet[] => [
                { key: 'team', label: 'Team', description: 'Owner', loadValues },
            ]
            const { rerender } = render(<ServerConsumer facets={teamFacet(() => oldTeams.promise)} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(document.querySelector('[role="status"]')).toHaveTextContent('Loading values…'))

            rerender(<ServerConsumer facets={[PLAN]} />)
            oldTeams.resolve([{ value: 'old', label: 'Old project team' }])
            rerender(<ServerConsumer facets={teamFacet(async () => [{ value: 'new', label: 'New project team' }])} />)
            await waitFor(() => expect(suggestions()).toEqual(['New project team']))
        })

        it('keeps a load from an unmounted bar out of the next bar with the same data attr', async () => {
            const oldTeams = deferred<FacetValueOption[]>()
            const teamFacet = (loadValues: LoadFacetValues): ServerFacet[] => [
                { key: 'team', label: 'Team', description: 'Owner', loadValues },
            ]
            const { unmount } = render(<ServerConsumer facets={teamFacet(() => oldTeams.promise)} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(document.querySelector('[role="status"]')).toHaveTextContent('Loading values…'))
            unmount()

            render(<ServerConsumer facets={teamFacet(async () => [{ value: 'new', label: 'New project team' }])} />)
            await user.click(input())
            await user.paste('team:')
            await waitFor(() => expect(suggestions()).toEqual(['New project team']))

            await act(async () => {
                oldTeams.resolve([{ value: 'old', label: 'Old project team' }])
                await oldTeams.promise
            })
            expect(suggestions()).toEqual(['New project team'])
        })

        it('loads values for text the consumer sets while the bar is open', async () => {
            const facets: ServerFacet[] = [
                {
                    key: 'team',
                    label: 'Team',
                    description: 'Owner',
                    loadValues: async () => [{ value: 't-1', label: 'Growth' }],
                },
            ]
            const bar = (text: string): JSX.Element => (
                <FacetSearchBar
                    facets={facets}
                    value={{ filters: [], text }}
                    onChange={() => {}}
                    placeholder="Search"
                    dataAttr="controlled-search"
                />
            )
            const { rerender } = render(bar(''))
            const user = userEvent.setup()
            await user.click(input())

            rerender(bar('gro'))
            await waitFor(() => expect(suggestions()).toEqual(['Search for "gro"', 'Team: Growth']))
        })

        it('shows what the loader returns for the exact text typed', async () => {
            const loadValues = async (search: string): Promise<FacetValueOption[]> =>
                ({
                    X: [{ value: 'id-1', label: 'Upper' }],
                    x: [{ value: 'id-2', label: 'Lower' }],
                })[search] ?? []
            render(
                <ServerConsumer facets={[{ key: 'code', label: 'Code', description: 'Case-sensitive', loadValues }]} />
            )
            const user = userEvent.setup()
            await user.click(input())
            await user.paste('code:X')
            await waitFor(() => expect(suggestions()).toEqual(['Upper']))

            await user.keyboard('{Backspace}x')
            await waitFor(() => expect(suggestions()).toEqual(['Lower']))
        })

        it('keeps suggestions apart when a facet key and a value share a dash', async () => {
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            const facets: ServerFacet[] = [
                { key: 'a', label: 'A', description: 'First', values: [{ value: 'b-c', label: 'Shared one' }] },
                { key: 'a-b', label: 'A b', description: 'Second', values: [{ value: 'c', label: 'Shared two' }] },
            ]
            render(<ServerConsumer facets={facets} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('shared')
            expect(suggestions()).toEqual(['Search for "shared"', 'A: Shared one', 'A b: Shared two'])
            expect(consoleError.mock.calls.flat().join(' ')).not.toContain('same key')
        })

        it('keeps values that differ only by case apart, through the URL too', async () => {
            const codes: ServerFacet = {
                key: 'code',
                label: 'Code',
                description: 'Case-sensitive id',
                values: [{ value: 'X' }, { value: 'x' }],
            }
            render(<ServerConsumer url="code:X" facets={[codes]} />)
            const user = userEvent.setup()
            await user.click(input())
            await user.keyboard('code:{Enter}')
            expect(shown('url')).toEqual('code:X code:x')
            expect(parseFacetSearch(shown('url'), [codes]).filters).toHaveLength(2)
        })
    })
})
