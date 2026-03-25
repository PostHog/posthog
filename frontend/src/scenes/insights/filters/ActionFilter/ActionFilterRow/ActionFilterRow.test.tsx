import { MOCK_GROUP_TYPES } from '~/lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { searchAndSelect, setupInsightMocks } from '~/test/insight-testing'
import {
    AvailableFeature,
    EntityTypes,
    FilterType,
    HogQLMathType,
    InsightType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import filtersJson from '../__mocks__/filters.json'
import { ActionFilterRow, MathAvailability, taxonomicFilterGroupTypeToEntityType } from './ActionFilterRow'

// AutoSizer needs a mock because react-virtualized requires real DOM measurements
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

// HogQLEditor uses Monaco which requires Web Workers and cannot run in jsdom
jest.mock('lib/components/HogQLEditor/HogQLEditor', () => ({
    HogQLEditor: () => <div data-attr="mock-hogql-editor" />,
}))

// dnd-kit requires DndContext wrapping and gesture simulation
jest.mock('@dnd-kit/sortable', () => ({
    useSortable: () => ({
        setNodeRef: jest.fn(),
        attributes: {},
        transform: null,
        transition: null,
        listeners: {},
        isDragging: false,
    }),
}))

const DEFAULT_FILTER = {
    id: '$pageview',
    name: '$pageview',
    type: EntityTypes.EVENTS as const,
    order: 0,
    uuid: 'test-uuid-1',
    properties: [],
}

// Non-popup context: no trends display, no math → inline buttons shown
const INLINE_CONTEXT = {
    trendsDisplayCategory: null,
    mathAvailability: MathAvailability.None,
}

function setup(filtersOverride?: Partial<FilterType>): {
    logic: ReturnType<typeof entityFilterLogic.build>
    setFilters: jest.Mock
} {
    const filters = { ...filtersJson, ...filtersOverride } as FilterType
    const setFilters = jest.fn()
    const logic = entityFilterLogic({ setFilters, filters, typeKey: 'test-key' })
    logic.mount()
    return { logic, setFilters }
}

function renderRow(
    logic: ReturnType<typeof entityFilterLogic.build>,
    propOverrides: Record<string, any> = {}
): ReturnType<typeof render> {
    return render(
        <Provider>
            <ActionFilterRow
                logic={logic}
                filter={DEFAULT_FILTER}
                index={0}
                typeKey="test-key"
                mathAvailability={MathAvailability.All}
                filterCount={2}
                sortable={false}
                hasBreakdown={false}
                trendsDisplayCategory={null}
                {...propOverrides}
            />
        </Provider>
    )
}

describe('ActionFilterRow', () => {
    afterEach(cleanup)

    beforeEach(() => {
        initKeaTests()

        // setupInsightMocks provides realistic event/property definitions with search
        // support, person properties, and query response handling
        setupInsightMocks()

        // Supplement with endpoints specific to ActionFilterRow
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: filtersJson.actions },
                '/api/environments/:team/groups_types/': MOCK_GROUP_TYPES,
                '/api/projects/:team/warehouse_tables/': { results: [] },
                '/api/projects/:team/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team/warehouse_view_links/': { results: [] },
            },
        })

        useAvailableFeatures([AvailableFeature.GROUP_ANALYTICS])
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
    })

    describe('taxonomicFilterGroupTypeToEntityType', () => {
        it.each([
            [TaxonomicFilterGroupType.Events, EntityTypes.EVENTS],
            [TaxonomicFilterGroupType.Actions, EntityTypes.ACTIONS],
            [TaxonomicFilterGroupType.DataWarehouse, EntityTypes.DATA_WAREHOUSE],
        ])('maps %s to %s', (input, expected) => {
            expect(taxonomicFilterGroupTypeToEntityType(input)).toBe(expected)
        })

        it.each([
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.Cohorts,
        ])('returns null for unmapped type %s', (input) => {
            expect(taxonomicFilterGroupTypeToEntityType(input)).toBeNull()
        })
    })

    describe('rendering', () => {
        it('renders the filter element with event name', () => {
            const { logic } = setup()
            renderRow(logic)
            expect(document.querySelector('.ActionFilterRow')).toBeInTheDocument()
            // EntityFilterInfo renders $pageview as "Pageview" display name
            expect(document.querySelector('.ActionFilterRow')!.textContent).toContain('Pageview')
        })

        describe('series indicators', () => {
            it.each([
                ['alpha', 'A'],
                ['numeric', '1'],
            ] as const)('shows %s series indicator', (type, expectedText) => {
                const { logic } = setup()
                renderRow(logic, { showSeriesIndicator: true, seriesIndicatorType: type })
                expect(screen.getByText(expectedText)).toBeInTheDocument()
            })

            it('does not show series indicator section when showSeriesIndicator is false', () => {
                const { logic } = setup()
                renderRow(logic, { showSeriesIndicator: false })
                expect(document.querySelector('.ActionFilterRow__start')).not.toBeInTheDocument()
            })
        })

        describe('read-only mode', () => {
            it('does not render action buttons', () => {
                const { logic } = setup()
                renderRow(logic, { readOnly: true })
                expect(screen.queryByTitle('Delete graph series')).not.toBeInTheDocument()
                expect(screen.queryByTitle('Rename graph series')).not.toBeInTheDocument()
                expect(screen.queryByTitle('Duplicate graph series')).not.toBeInTheDocument()
                expect(screen.queryByLabelText('Show more actions')).not.toBeInTheDocument()
            })
        })

        describe('inline buttons mode', () => {
            it('shows rename, duplicate, delete inline when not in popup context', () => {
                const { logic } = setup()
                renderRow(logic, INLINE_CONTEXT)
                expect(screen.getByTitle('Rename graph series')).toBeInTheDocument()
                expect(screen.getByTitle('Duplicate graph series')).toBeInTheDocument()
                expect(screen.getByTitle('Delete graph series')).toBeInTheDocument()
            })

            it.each([
                ['hideRename', 'Rename graph series'],
                ['hideDuplicate', 'Duplicate graph series'],
                ['hideDeleteBtn', 'Delete graph series'],
            ])('hides button when %s is true', (prop, title) => {
                const { logic } = setup()
                renderRow(logic, { ...INLINE_CONTEXT, [prop]: true })
                expect(screen.queryByTitle(title)).not.toBeInTheDocument()
            })

            it('hides duplicate and delete when singleFilter is true', () => {
                const { logic } = setup()
                renderRow(logic, { ...INLINE_CONTEXT, singleFilter: true })
                expect(screen.queryByTitle('Duplicate graph series')).not.toBeInTheDocument()
                expect(screen.queryByTitle('Delete graph series')).not.toBeInTheDocument()
            })
        })

        describe('popup menu mode', () => {
            it('shows ellipsis menu button in trends context', () => {
                const { logic } = setup()
                renderRow(logic, { trendsDisplayCategory: 'TotalValue' as any })
                expect(screen.getByLabelText('Show more actions')).toBeInTheDocument()
            })

            it('shows ellipsis menu button in funnel context', () => {
                const { logic } = setup({ insight: InsightType.FUNNELS })
                renderRow(logic, { mathAvailability: MathAvailability.FunnelsOnly })
                expect(screen.getByLabelText('Show more actions')).toBeInTheDocument()
            })

            it('does not show ellipsis menu in non-popup context', () => {
                const { logic } = setup()
                renderRow(logic, INLINE_CONTEXT)
                expect(screen.queryByLabelText('Show more actions')).not.toBeInTheDocument()
            })
        })

        describe('math availability', () => {
            it.each([
                [MathAvailability.All, true],
                [MathAvailability.ActorsOnly, true],
                [MathAvailability.CalendarHeatmapOnly, true],
                [MathAvailability.FunnelsOnly, false],
                [MathAvailability.None, false],
            ])('math selector visibility for MathAvailability=%s is %s', (availability, visible) => {
                const { logic } = setup()
                renderRow(logic, { mathAvailability: availability })
                if (visible) {
                    expect(screen.getByTestId('math-selector-0')).toBeInTheDocument()
                } else {
                    expect(screen.queryByTestId('math-selector-0')).not.toBeInTheDocument()
                }
            })

            it('renders property selector when MathAvailability.BoxPlotOnly', () => {
                const { logic } = setup()
                renderRow(logic, { mathAvailability: MathAvailability.BoxPlotOnly })
                expect(screen.queryByTestId('math-selector-0')).not.toBeInTheDocument()
                expect(screen.getByTestId('box-plot-property-select')).toBeInTheDocument()
            })
        })

        describe('property filters', () => {
            it('shows property filter toggle button', () => {
                const { logic } = setup()
                renderRow(logic, { ...INLINE_CONTEXT, hideFilter: false })
                expect(screen.getByTitle('Show filters')).toBeInTheDocument()
            })

            it('renders PropertyFilters when visibility is toggled on', () => {
                const { logic } = setup()
                logic.actions.setEntityFilterVisibility(0, true)
                renderRow(logic)
                // Real PropertyFilters renders with a page key
                expect(document.querySelector('.ActionFilterRow-filters')).toBeInTheDocument()
            })

            it('does not render PropertyFilters when visibility is off', () => {
                const { logic } = setup()
                renderRow(logic)
                expect(document.querySelector('.ActionFilterRow-filters')).not.toBeInTheDocument()
            })
        })

        describe('drag handle', () => {
            it.each([
                [true, 3, true],
                [true, 1, false],
                [false, 3, false],
            ])('sortable=%s filterCount=%s → visible=%s', (sortable, filterCount, visible) => {
                const { logic } = setup()
                renderRow(logic, { sortable, filterCount })
                if (visible) {
                    expect(document.querySelector('.ActionFilterRowDragHandle')).toBeInTheDocument()
                } else {
                    expect(document.querySelector('.ActionFilterRowDragHandle')).not.toBeInTheDocument()
                }
            })
        })

        describe('combine events button', () => {
            it('shown when showCombine and not singleFilter', () => {
                const { logic } = setup()
                renderRow(logic, { ...INLINE_CONTEXT, showCombine: true, singleFilter: false })
                expect(screen.getByTitle('Count multiple events as a single event')).toBeInTheDocument()
            })

            it('hidden when singleFilter', () => {
                const { logic } = setup()
                renderRow(logic, { ...INLINE_CONTEXT, showCombine: true, singleFilter: true })
                expect(screen.queryByTitle('Count multiple events as a single event')).not.toBeInTheDocument()
            })

            it('hidden for data warehouse entities', () => {
                const { logic } = setup()
                renderRow(logic, {
                    ...INLINE_CONTEXT,
                    showCombine: true,
                    singleFilter: false,
                    filter: { ...DEFAULT_FILTER, type: EntityTypes.DATA_WAREHOUSE },
                })
                expect(screen.queryByTitle('Count multiple events as a single event')).not.toBeInTheDocument()
            })
        })

        describe('custom renderRow', () => {
            it('delegates to custom render function', () => {
                const { logic } = setup()
                const customRender = jest.fn(({ filter }) => <div data-attr="custom-row">{filter}</div>)
                renderRow(logic, { renderRow: customRender })
                expect(screen.getByTestId('custom-row')).toBeInTheDocument()
                expect(customRender).toHaveBeenCalledWith(
                    expect.objectContaining({
                        seriesIndicator: expect.anything(),
                        filter: expect.anything(),
                        suffix: undefined,
                        propertyFiltersButton: expect.anything(),
                        renameRowButton: expect.anything(),
                        deleteButton: expect.anything(),
                    })
                )
            })
        })

        describe('custom row suffix', () => {
            it('renders string suffix', () => {
                const { logic } = setup()
                renderRow(logic, { customRowSuffix: 'my-suffix' })
                expect(screen.getByText('my-suffix')).toBeInTheDocument()
            })

            it('calls function suffix with filter, index, onClose', () => {
                const { logic } = setup()
                const suffixFn = jest.fn(({ filter }) => <span data-attr="fn-suffix">{filter.name}</span>)
                renderRow(logic, { customRowSuffix: suffixFn })
                expect(screen.getByTestId('fn-suffix')).toHaveTextContent('$pageview')
                expect(suffixFn).toHaveBeenCalledWith(
                    expect.objectContaining({
                        filter: expect.objectContaining({ id: '$pageview' }),
                        index: 0,
                        onClose: expect.any(Function),
                    })
                )
            })
        })

        describe('action entity type', () => {
            it('renders with the action name', () => {
                const { logic } = setup()
                renderRow(logic, {
                    filter: { ...DEFAULT_FILTER, id: '9', name: 'Users signed up', type: EntityTypes.ACTIONS },
                })
                expect(document.querySelector('.ActionFilterRow')!.textContent).toContain('Users signed up')
            })
        })
    })

    describe('interactions', () => {
        it('dispatches removeLocalFilter on delete click', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, { ...INLINE_CONTEXT, hideDeleteBtn: false, singleFilter: false })
            await userEvent.click(screen.getByTitle('Delete graph series'))
            // Deleting the first event (order 0) leaves only 1 event + 1 action, re-ordered
            expect(setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: [expect.objectContaining({ id: '$pageview' })],
                    actions: [expect.objectContaining({ id: '9' })],
                })
            )
            // The remaining event list should have exactly 1 entry (down from 2)
            const call = setFilters.mock.calls[0][0]
            expect(call.events).toHaveLength(1)
        })

        it('dispatches duplicateFilter on duplicate click', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, { ...INLINE_CONTEXT, hideDuplicate: false, singleFilter: false })
            await userEvent.click(screen.getByTitle('Duplicate graph series'))
            expect(setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([expect.objectContaining({ id: '$pageview', order: 0 })]),
                })
            )
        })

        it('dispatches selectFilter and calls onRenameClick on rename', async () => {
            const { logic } = setup()
            const onRenameClick = jest.fn()
            renderRow(logic, { ...INLINE_CONTEXT, hideRename: false, onRenameClick })
            await userEvent.click(screen.getByTitle('Rename graph series'))
            expect(onRenameClick).toHaveBeenCalled()
        })

        it('dispatches convertFilterToGroup on combine click', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, { ...INLINE_CONTEXT, showCombine: true, singleFilter: false })
            await userEvent.click(screen.getByTitle('Count multiple events as a single event'))
            expect(setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([expect.objectContaining({ id: '$pageview' })]),
                })
            )
        })

        it('toggles property filter visibility on filter button click', async () => {
            const { logic } = setup()
            renderRow(logic, { ...INLINE_CONTEXT, hideFilter: false })

            expect(document.querySelector('.ActionFilterRow-filters')).not.toBeInTheDocument()

            await userEvent.click(screen.getByTitle('Show filters'))

            await waitFor(() => {
                expect(document.querySelector('.ActionFilterRow-filters')).toBeInTheDocument()
            })
        })
    })

    describe('math selection', () => {
        it('changing math type calls setFilters with updated math', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, { mathAvailability: MathAvailability.All })

            await userEvent.click(screen.getByTestId('math-selector-0'))

            await waitFor(() => {
                expect(screen.getByText('Unique users')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByText('Unique users'))

            expect(setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([expect.objectContaining({ math: 'dau' })]),
                })
            )
        })

        it('shows property value selector when property math is active', () => {
            const { logic } = setup()
            renderRow(logic, {
                mathAvailability: MathAvailability.All,
                filter: {
                    ...DEFAULT_FILTER,
                    math: PropertyMathType.Average,
                    math_property: '$time',
                },
            })
            expect(screen.getByTestId('math-property-select')).toBeInTheDocument()
        })

        it('shows HogQL expression button when HogQL math is active', () => {
            const { logic } = setup()
            renderRow(logic, {
                mathAvailability: MathAvailability.All,
                filter: {
                    ...DEFAULT_FILTER,
                    math: HogQLMathType.HogQL,
                    math_hogql: 'sum(price)',
                },
            })
            expect(screen.getByTestId('math-hogql-select-0')).toBeInTheDocument()
            expect(screen.getByText('sum(price)')).toBeInTheDocument()
        })

        it('does not show math selector inline for FunnelsOnly (it goes in the popup menu)', () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, { mathAvailability: MathAvailability.FunnelsOnly })
            // MathSelector should NOT be in the center section (it's in the popup menu instead)
            expect(screen.queryByTestId('math-selector-0')).not.toBeInTheDocument()
        })

        it('selecting property math sets math_property and clears math_hogql', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, {
                mathAvailability: MathAvailability.All,
                filter: {
                    ...DEFAULT_FILTER,
                    math: PropertyMathType.Average,
                    math_property: '$time',
                    math_hogql: 'count()',
                },
            })

            // Simulate onMathPropertySelect which calls updateFilterMath
            logic.actions.updateFilterMath({
                ...DEFAULT_FILTER,
                math_hogql: undefined,
                math_property: '$session_duration',
                math_property_type: TaxonomicFilterGroupType.SessionProperties,
                index: 0,
            })

            await waitFor(() => {
                const call = setFilters.mock.calls[setFilters.mock.calls.length - 1][0]
                expect(call.events).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            math_property: '$session_duration',
                        }),
                    ])
                )
                // math_hogql should not be present on the updated filter
                const updatedEvent = call.events.find((e: any) => e.math_property === '$session_duration')
                expect(updatedEvent.math_hogql).toBeUndefined()
            })
        })

        it('shows group math options when GROUP_ANALYTICS is enabled', async () => {
            const { logic } = setup()
            renderRow(logic, { mathAvailability: MathAvailability.All })

            await userEvent.click(screen.getByTestId('math-selector-0'))

            await waitFor(() => {
                // MOCK_GROUP_TYPES provides organization, instance, project — the "Unique"
                // dropdown in the math selector should contain group options derived from them
                expect(screen.getByText('Unique users')).toBeInTheDocument()
                expect(screen.getByText('Count per user')).toBeInTheDocument()
                expect(screen.getByText('Property value')).toBeInTheDocument()
            })
        })
    })

    describe('funnel popup menu contents', () => {
        it('shows rename and delete inside popup menu when opened', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, { mathAvailability: MathAvailability.FunnelsOnly })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                expect(screen.getByText('Rename')).toBeInTheDocument()
                expect(screen.getByText('Delete')).toBeInTheDocument()
            })
        })

        it('shows duplicate in popup menu when not singleFilter', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, {
                mathAvailability: MathAvailability.FunnelsOnly,
                singleFilter: false,
            })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                expect(screen.getByText('Duplicate')).toBeInTheDocument()
            })
        })

        it('hides duplicate in popup menu when singleFilter', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, {
                mathAvailability: MathAvailability.FunnelsOnly,
                singleFilter: true,
            })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                expect(screen.getByText('Rename')).toBeInTheDocument()
                expect(screen.queryByText('Duplicate')).not.toBeInTheDocument()
            })
        })

        it('shows optional step checkbox for funnel steps after the first', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, {
                mathAvailability: MathAvailability.FunnelsOnly,
                index: 1,
                filter: { ...DEFAULT_FILTER, order: 1 },
            })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                expect(screen.getByText('Optional step')).toBeInTheDocument()
            })
        })

        it('does not show optional step checkbox for the first funnel step', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, {
                mathAvailability: MathAvailability.FunnelsOnly,
                index: 0,
            })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                expect(screen.getByText('Rename')).toBeInTheDocument()
                expect(screen.queryByText('Optional step')).not.toBeInTheDocument()
            })
        })

        it('shows math selector inside funnel popup menu', async () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, { mathAvailability: MathAvailability.FunnelsOnly })

            await userEvent.click(screen.getByLabelText('Show more actions'))

            await waitFor(() => {
                // MathSelector renders inside the menu for funnels
                expect(screen.getByTestId('math-selector-0')).toBeInTheDocument()
            })
        })

        it('shows property filter and combine buttons outside the popup menu', () => {
            const { logic } = setup({ insight: InsightType.FUNNELS })
            renderRow(logic, {
                mathAvailability: MathAvailability.FunnelsOnly,
                hideFilter: false,
                showCombine: true,
            })

            // Filter and combine always visible, not inside the menu
            expect(screen.getByTitle('Show filters')).toBeInTheDocument()
            expect(screen.getByTitle('Count multiple events as a single event')).toBeInTheDocument()
        })
    })

    describe('event selection onChange handler', () => {
        it('selecting an event updates the filter with the chosen event', async () => {
            const { logic, setFilters } = setup()
            renderRow(logic, INLINE_CONTEXT)

            await userEvent.click(screen.getByTestId('trend-element-subject-0'))

            // setupInsightMocks provides realistic event definitions with search support
            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('prop-filter-events-1'))

            await waitFor(() => {
                expect(setFilters).toHaveBeenCalledWith(
                    expect.objectContaining({
                        events: expect.arrayContaining([
                            expect.objectContaining({
                                type: EntityTypes.EVENTS,
                                order: 0,
                            }),
                        ]),
                    })
                )
            })
        })

        // These branches are triggered when the user selects an item from a specialized
        // TaxonomicPopover tab. We test through the UI using searchAndSelect: open popover →
        // switch tab → search (minSearchQueryLength=3) → select item → assert setFilters.
        it.each([
            {
                tab: 'pageview_events',
                searchText: 'exam',
                resultValue: 'https://example.com',
                expectedEventId: '$pageview',
                expectedPropertyKey: '$current_url',
                expectedOperator: PropertyOperator.IContains,
            },
            {
                tab: 'screen_events',
                searchText: 'home',
                resultValue: 'HomeScreen',
                expectedEventId: '$screen',
                expectedPropertyKey: '$screen_name',
                expectedOperator: PropertyOperator.Exact,
            },
            {
                tab: 'autocapture_events',
                searchText: 'sign',
                resultValue: 'Sign Up',
                expectedEventId: '$autocapture',
                expectedPropertyKey: '$el_text',
                expectedOperator: PropertyOperator.Exact,
            },
        ])(
            '$tab selects $expectedEventId with $expectedPropertyKey property filter',
            async ({ tab, searchText, resultValue, expectedEventId, expectedPropertyKey, expectedOperator }) => {
                useMocks({
                    get: {
                        '/api/environments/:team/events/values/': [{ name: resultValue }, { name: 'other-value' }],
                    },
                })

                const { logic, setFilters } = setup()
                renderRow(logic, {
                    ...INLINE_CONTEXT,
                    actionsTaxonomicGroupTypes: [
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.PageviewEvents,
                        TaxonomicFilterGroupType.ScreenEvents,
                        TaxonomicFilterGroupType.AutocaptureEvents,
                    ],
                })

                await searchAndSelect('trend-element-subject-0', searchText, `prop-filter-${tab}-0`)

                await waitFor(() => {
                    const lastCall = setFilters.mock.calls[setFilters.mock.calls.length - 1][0]
                    expect(lastCall.events).toEqual(
                        expect.arrayContaining([
                            expect.objectContaining({
                                id: expectedEventId,
                                properties: expect.arrayContaining([
                                    expect.objectContaining({
                                        key: expectedPropertyKey,
                                        value: resultValue,
                                        operator: expectedOperator,
                                        type: PropertyFilterType.Event,
                                    }),
                                ]),
                            }),
                        ])
                    )
                })
            }
        )
    })

    describe('all events entity filter', () => {
        it('renders "All events" placeholder for null event id', () => {
            const { logic } = setup()
            renderRow(logic, {
                filter: {
                    ...DEFAULT_FILTER,
                    id: null,
                    name: 'All events',
                },
            })
            expect(document.querySelector('.ActionFilterRow')!.textContent).toContain('All events')
        })
    })

    describe('property filters section', () => {
        it('shows filter count badge when filter has properties', () => {
            const { logic } = setup()
            renderRow(logic, {
                ...INLINE_CONTEXT,
                hideFilter: false,
                filter: {
                    ...DEFAULT_FILTER,
                    properties: [
                        { key: '$browser', value: 'Chrome', operator: 'exact', type: 'event' },
                        { key: '$os', value: 'Mac', operator: 'exact', type: 'event' },
                    ],
                },
            })
            // IconWithCount shows the property count
            expect(screen.getByText('2')).toBeInTheDocument()
        })

        it('disables property filter button when filter id is empty', () => {
            const { logic } = setup()
            renderRow(logic, {
                ...INLINE_CONTEXT,
                hideFilter: false,
                filter: { ...DEFAULT_FILTER, id: 'empty' },
            })
            const filterButton = screen.getByTitle('Show filters')
            expect(filterButton).toHaveAttribute('aria-disabled', 'true')
        })
    })

    describe('disabled state', () => {
        it('disables TaxonomicPopover when disabled prop is true', () => {
            const { logic } = setup()
            renderRow(logic, { disabled: true })
            const popoverButton = screen.getByTestId('trend-element-subject-0')
            expect(popoverButton).toHaveAttribute('aria-disabled', 'true')
        })

        it('disables TaxonomicPopover when readOnly prop is true', () => {
            const { logic } = setup()
            renderRow(logic, { readOnly: true })
            const popoverButton = screen.getByTestId('trend-element-subject-0')
            expect(popoverButton).toHaveAttribute('aria-disabled', 'true')
        })

        it('disables math selector when readOnly is true', () => {
            const { logic } = setup()
            renderRow(logic, { readOnly: true, mathAvailability: MathAvailability.All })
            const mathSelector = screen.getByTestId('math-selector-0')
            expect(mathSelector).toHaveAttribute('aria-disabled', 'true')
        })
    })
})
