import { RenderResult, act, cleanup, fireEvent, render, renderHook, waitFor } from '@testing-library/react'
import { combineUrl, router } from 'kea-router'

import { LemonDropdown } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { performQuery } from '~/queries/query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContextColumnComponent } from '~/queries/types'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'
import { AIObservabilityTraces, useTracesQueryContext } from './AIObservabilityTracesScene'
import { traceDrawerLogic } from './redesign/trace/traceDrawerLogic'

jest.mock('lib/utils/newInternalTab')
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))
jest.mock('~/queries/nodes/DataTable/DataTable', () => {
    const actual = jest.requireActual('~/queries/nodes/DataTable/DataTable')
    return { ...actual, DataTable: jest.fn(actual.DataTable) }
})

const PERSON = {
    uuid: 'person-1',
    distinct_id: 'user-1',
    created_at: '2026-01-01T12:00:00Z',
    properties: { email: 'person@example.com' },
}
const TRACE_RECORD = { result: { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z', events: [] } }
const TRACE_PATH = urls.aiObservabilityTrace('trace-1')
const LINK_CELL_PATH = urls.aiObservabilitySessions()

function renderRow(record: unknown): { plainCell: HTMLElement; linkCell: HTMLElement } {
    const { result } = renderHook(() => useTracesQueryContext())
    const { getByTestId } = render(
        <table>
            <tbody>
                <tr {...(result.current.rowProps?.(record) ?? {})}>
                    <td data-attr="plain-cell">plain</td>
                    <td>
                        <Link to={LINK_CELL_PATH} data-attr="link-cell">
                            link
                        </Link>
                    </td>
                </tr>
            </tbody>
        </table>
    )
    return { plainCell: getByTestId('plain-cell'), linkCell: getByTestId('link-cell') }
}

function renderCell(columnName: string, record: unknown): string {
    const { result } = renderHook(() => useTracesQueryContext())
    const Column = result.current.columns?.[columnName]?.render as QueryContextColumnComponent
    const { container } = render(
        <Column
            record={record}
            columnName={columnName}
            value={undefined}
            query={{} as DataTableNode}
            recordIndex={0}
            rowCount={1}
        />
    )
    return container.textContent ?? ''
}

const LIST_PATH = urls.aiObservabilityTraces()
const DRAWER_TIMESTAMP = '2026-01-01T11:55:00Z'
const OPEN_ROW_CLASS = 'LemonTable__row--status-highlighted'
const TRACES = [
    { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z', events: [], traceName: 'first', person: PERSON },
    { id: 'trace-2', createdAt: '2026-01-01T13:00:00Z', events: [], traceName: 'second', person: PERSON },
]

function tracesRequests(): number {
    return jest.mocked(performQuery).mock.calls.filter(([query]) => query.kind === NodeKind.TracesQuery).length
}

async function renderTraces({ flag = true, url = LIST_PATH } = {}): Promise<RenderResult> {
    initKeaTests()
    localStorage.clear()
    jest.mocked(newInternalTab).mockClear()
    jest.mocked(DataTable).mockClear()
    jest.mocked(performQuery).mockReset()
    jest.mocked(performQuery).mockImplementation(async (query) =>
        query.kind === NodeKind.TracesQuery ? { results: TRACES } : { results: [] }
    )
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
        [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: flag,
    })
    panelLayoutLogic.mount()
    router.actions.push(url)
    const view = render(<AIObservabilityTraces />)
    await waitFor(() => expect(view.container.querySelector('[data-attr="trace-id-link"]')).not.toBeNull())
    return view
}

function tableRow(view: RenderResult, traceName: string): HTMLElement {
    const row = view.getByText(traceName).closest('tr')
    if (!row) {
        throw new Error(`No row for ${traceName}`)
    }
    return row
}

function firstCell(view: RenderResult): HTMLElement {
    return tableRow(view, 'first').querySelectorAll('td')[0]
}

function firstLink(view: RenderResult, dataAttr: string): HTMLElement {
    const link = view.container.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`)
    if (!link) {
        throw new Error(`No ${dataAttr}`)
    }
    return link
}

function lastContext(): NonNullable<Parameters<typeof DataTable>[0]['context']> {
    const context = jest.mocked(DataTable).mock.lastCall?.[0].context
    if (!context) {
        throw new Error('DataTable was not rendered')
    }
    return context
}

describe('AIObservabilityTracesScene', () => {
    describe('row navigation', () => {
        let pathnameBeforeClick: string

        beforeEach(() => {
            cleanup()
            initKeaTests()
            jest.mocked(newInternalTab).mockClear()
            pathnameBeforeClick = router.values.location.pathname
        })

        it('navigates to the trace detail view when a plain cell is clicked', () => {
            const { plainCell } = renderRow(TRACE_RECORD)

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toContain(TRACE_PATH)
            expect(router.values.searchParams).toMatchObject({ back_to: 'traces', timestamp: '2026-01-01T11:55:00Z' })
            expect(newInternalTab).not.toHaveBeenCalled()
        })

        it.each([
            ['meta-click', (cell: HTMLElement): boolean => fireEvent.click(cell, { metaKey: true })],
            ['ctrl-click', (cell: HTMLElement): boolean => fireEvent.click(cell, { ctrlKey: true })],
            [
                'middle click',
                (cell: HTMLElement): boolean =>
                    fireEvent(cell, new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 })),
            ],
        ])('opens the trace detail view in a new tab on %s', (_name, clickCell) => {
            const { plainCell } = renderRow(TRACE_RECORD)

            clickCell(plainCell)

            expect(router.values.location.pathname).toBe(pathnameBeforeClick)
            expect(newInternalTab).toHaveBeenCalledWith(expect.stringContaining(TRACE_PATH))
        })

        it('leaves a cell with its own link to handle its click', () => {
            const { linkCell } = renderRow(TRACE_RECORD)

            fireEvent.click(linkCell)

            expect(router.values.location.pathname).toContain(LINK_CELL_PATH)
            expect(newInternalTab).not.toHaveBeenCalled()
        })

        it.each([
            ['has no createdAt', { id: 'trace-1', events: [] }],
            ['has an unparseable createdAt', { id: 'trace-1', createdAt: 'not a date', events: [] }],
        ])('leaves the timestamp out of the trace detail url when the row %s', (_name, result) => {
            const { plainCell } = renderRow({ result })

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toContain(TRACE_PATH)
            expect(router.values.searchParams).not.toHaveProperty('timestamp')
        })

        it.each([
            ['a label row', { label: 'January 1' }],
            ['an array result', { result: ['trace-1'] }],
            ['a result without an id', { result: { createdAt: '2026-01-01T12:00:00Z' } }],
        ])('does not make the row clickable for %s', (_name, record) => {
            const { plainCell } = renderRow(record)

            fireEvent.click(plainCell)

            expect(router.values.location.pathname).toBe(pathnameBeforeClick)
            expect(newInternalTab).not.toHaveBeenCalled()
        })
    })

    describe('opening the trace drawer from the list', () => {
        afterEach(cleanup)

        it.each([
            ['the row', firstCell],
            ['the ID link', (view: RenderResult): HTMLElement => firstLink(view, 'trace-id-link')],
            ['the name link', (view: RenderResult): HTMLElement => firstLink(view, 'trace-name-link')],
        ])('opens the drawer on a plain click on %s', async (_name, target) => {
            const view = await renderTraces()

            fireEvent.click(target(view))

            expect(router.values.location.pathname).toContain(LIST_PATH)
            expect(router.values.searchParams).toMatchObject({ trace: 'trace-1', ts: DRAWER_TIMESTAMP })
            expect(router.values.searchParams).not.toHaveProperty('back_to')
            expect(newInternalTab).not.toHaveBeenCalled()
        })

        it.each([
            ['closed', LIST_PATH],
            [
                'open on another trace',
                combineUrl(LIST_PATH, { trace: 'trace-2', ts: DRAWER_TIMESTAMP, step: 'gen-1' }).url,
            ],
        ])('opens the page in a new tab on a Cmd-click on the row with the drawer %s', async (_name, url) => {
            const view = await renderTraces({ url })
            const listUrl = router.values.currentLocation

            fireEvent.click(firstCell(view), { metaKey: true })

            expect(router.values.currentLocation).toEqual(listUrl)
            const pageUrl = combineUrl(jest.mocked(newInternalTab).mock.lastCall?.[0] ?? '')
            expect(pageUrl.pathname).toContain(TRACE_PATH)
            expect(pageUrl.searchParams).toMatchObject({ back_to: 'traces' })
            expect(pageUrl.searchParams).not.toHaveProperty('trace')
            expect(pageUrl.searchParams).not.toHaveProperty('ts')
            expect(pageUrl.searchParams).not.toHaveProperty('step')
        })

        it('leaves the drawer params out of the trace links', async () => {
            const view = await renderTraces({
                url: combineUrl(LIST_PATH, { trace: 'trace-2', ts: DRAWER_TIMESTAMP, step: 'gen-1' }).url,
            })

            const { searchParams } = combineUrl(firstLink(view, 'trace-id-link').getAttribute('href') ?? '')

            expect(searchParams).toMatchObject({ back_to: 'traces' })
            expect(searchParams).not.toHaveProperty('trace')
            expect(searchParams).not.toHaveProperty('step')
        })

        it('leaves a click inside an overlay opened from a cell to the overlay', async () => {
            await renderTraces()
            const onOverlayClick = jest.fn()
            const { getByTestId } = render(
                <table>
                    <tbody>
                        <tr {...(lastContext().rowProps?.({ result: TRACES[0] }) ?? {})}>
                            <td>
                                <LemonDropdown
                                    visible
                                    overlay={
                                        <div data-attr="overlay-row" onClick={onOverlayClick}>
                                            copy
                                        </div>
                                    }
                                >
                                    <span>open</span>
                                </LemonDropdown>
                            </td>
                        </tr>
                    </tbody>
                </table>
            )

            fireEvent.click(getByTestId('overlay-row'))

            expect(onOverlayClick).toHaveBeenCalledTimes(1)
            expect(router.values.searchParams).not.toHaveProperty('trace')
        })

        it('leaves a Cmd-click on the ID link for the browser to open the page in a new tab', async () => {
            const view = await renderTraces()
            const link = firstLink(view, 'trace-id-link')

            const browserHandlesIt = fireEvent.click(link, { metaKey: true })

            expect(browserHandlesIt).toBe(true)
            expect(link.getAttribute('href')).toContain(TRACE_PATH)
            expect(router.values.searchParams).not.toHaveProperty('trace')
        })

        it('leaves a click on the person link alone', async () => {
            const view = await renderTraces()
            const personLink = tableRow(view, 'first').querySelector<HTMLElement>('a[href*="/person/"]')
            if (!personLink) {
                throw new Error('No person link')
            }

            fireEvent.click(personLink)

            expect(router.values.searchParams).not.toHaveProperty('trace')
        })

        it('closes back to the list and gives focus to the row that opened the panel, however far it stepped', async () => {
            const view = await renderTraces()
            act(() => panelLayoutLogic.actions.setMainContentRect(document.body.getBoundingClientRect()))
            const logic = traceDrawerLogic({ listId: 'traces' })
            await waitFor(() => expect(logic.values.rows).toHaveLength(2))

            fireEvent.click(firstCell(view))

            expect(document.activeElement).toBe(firstLink(view, 'trace-drawer'))

            fireEvent.click(firstLink(view, 'trace-drawer-next'))
            expect(router.values.searchParams).toMatchObject({ trace: 'trace-2' })
            fireEvent.click(firstLink(view, 'trace-drawer-close'))

            await waitFor(() => expect(view.container.querySelector('[data-attr="trace-drawer"]')).toBeNull())
            expect(router.values.searchParams.trace).toBeUndefined()
            expect(document.activeElement).toBe(firstLink(view, 'trace-id-link'))
        })

        it('marks only the open row', async () => {
            const view = await renderTraces({ url: combineUrl(LIST_PATH, { trace: 'trace-2' }).url })

            expect(tableRow(view, 'second').className).toContain(OPEN_ROW_CLASS)
            expect(tableRow(view, 'first').className).not.toContain(OPEN_ROW_CLASS)
        })

        it('keeps pushing the page url when the flag is off', async () => {
            const view = await renderTraces({ flag: false })

            fireEvent.click(firstCell(view))

            expect(router.values.location.pathname).toContain(TRACE_PATH)
            expect(router.values.searchParams).toMatchObject({ back_to: 'traces', timestamp: DRAWER_TIMESTAMP })
            expect(router.values.searchParams).not.toHaveProperty('trace')
        })

        it('keeps the drawer params through a filter change and does not query for writing them', async () => {
            const view = await renderTraces()

            fireEvent.click(firstCell(view))
            act(() => traceDrawerLogic({ listId: 'traces' }).actions.requestStep('gen-1', 'trace-1'))

            expect(tracesRequests()).toBe(1)

            act(() =>
                aiObservabilitySharedLogic.actions.setPropertyFilters([
                    {
                        type: PropertyFilterType.Event,
                        key: '$ai_model',
                        value: 'gpt-4',
                        operator: PropertyOperator.Exact,
                    },
                ])
            )

            await waitFor(() => expect(tracesRequests()).toBe(2))
            expect(router.values.searchParams).toMatchObject({
                trace: 'trace-1',
                ts: DRAWER_TIMESTAMP,
                step: 'gen-1',
            })
        })

        it('gives the drawer the loaded rows and keeps the table context when the response changes', async () => {
            await renderTraces()
            const logic = traceDrawerLogic({ listId: 'traces' })
            await waitFor(() => expect(logic.values.rows).toHaveLength(2))
            expect(logic.values.rows[0]).toEqual({ traceId: 'trace-1', timestamp: DRAWER_TIMESTAMP, stepId: null })
            const context = lastContext()

            act(() =>
                dataNodeLogic
                    .findMounted({ key: 'llm-analytics-traces' })
                    ?.actions.setResponse({ results: [TRACES[1]] })
            )

            expect(logic.values.rows).toEqual([{ traceId: 'trace-2', timestamp: '2026-01-01T12:55:00Z', stepId: null }])
            expect(lastContext()).toBe(context)
        })
    })

    // A row the response returned without a field `LLMTrace` types as present used to throw
    // in the cell renderer, which reaches the scene error boundary and blanks the whole list.
    describe('malformed cells', () => {
        beforeEach(() => {
            cleanup()
            initKeaTests()
        })

        it.each([
            ['id', { createdAt: '2026-01-01T12:00:00Z', events: [] }],
            ['createdAt', { id: 'trace-1', events: [] }],
            ['promptVersion', { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z' }],
            ['promptVersionId', { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z' }],
        ])('renders the %s cell as a dash instead of throwing', (columnName, record) => {
            expect(renderCell(columnName, record)).toBe('–')
        })

        it('renders the trace name as plain text when the row has no id', () => {
            expect(renderCell('traceName', { traceName: 'my trace' })).toBe('my trace')
        })

        it.each([
            [
                'the top-level error message and how many more there are',
                { id: 'trace-1', errorCount: 2, events: [{ properties: { $ai_error: 'RateLimitError' } }] },
                'RateLimitError+1',
            ],
            ['only the count when the error sits on a nested span', { id: 'trace-1', errorCount: 2 }, '2 errors'],
        ])('renders %s in the redesigned errors cell', (_name, record, expected) => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACES_USERS_REDESIGN], {
                [FEATURE_FLAGS.AI_OBSERVABILITY_TRACES_USERS_REDESIGN]: true,
            })

            expect(renderCell('errorCount', record)).toBe(expected)
        })
    })
})
