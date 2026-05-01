import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import {
    FunnelsQuery,
    LifecycleQuery,
    NodeKind,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, InsightShortId } from '~/types'

import { EditorFilters } from './EditorFilters'

// MaxTool has AI integration that requires additional setup — render children directly in tests
jest.mock('scenes/max/MaxTool', () => ({
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

function makeTrendsQuery(): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview', math: BaseMathType.TotalCount }],
    }
}

function makeDataWarehouseTrendsQuery(): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.DataWarehouseNode,
                id: 'warehouse_orders',
                table_name: 'warehouse_orders',
                name: 'Orders',
                timestamp_field: 'created_at',
                id_field: 'order_id',
                distinct_id_field: 'customer_id',
            },
        ],
    }
}

function makeLifecycleQuery(): LifecycleQuery {
    return {
        kind: NodeKind.LifecycleQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
    }
}

function makeStickinessQuery(): StickinessQuery {
    return {
        kind: NodeKind.StickinessQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview', math: BaseMathType.TotalCount }],
    }
}

function makeRetentionQuery(): RetentionQuery {
    return {
        kind: NodeKind.RetentionQuery,
        retentionFilter: {},
    }
}

function makeFunnelsQuery(): FunnelsQuery {
    return {
        kind: NodeKind.FunnelsQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview' }],
    }
}

function makePathsQuery(): PathsQuery {
    return { kind: NodeKind.PathsQuery, pathsFilter: {} }
}

function setupAndRender(
    query: TrendsQuery | LifecycleQuery | StickinessQuery | RetentionQuery | FunnelsQuery | PathsQuery
): void {
    insightLogic(insightProps).mount()
    insightDataLogic(insightProps).mount()
    funnelDataLogic(insightProps).mount()
    const vizDataLogic = insightVizDataLogic(insightProps)
    vizDataLogic.mount()
    vizDataLogic.actions.updateQuerySource(query)

    render(
        <Provider>
            <BindLogic logic={insightLogic} props={insightProps}>
                <EditorFilters query={query} showing embedded={false} />
            </BindLogic>
        </Provider>
    )
}

describe('EditorFilters', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
                '/api/users/@me': {},
                '/api/environments/:team_id/groups_types/': [],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'trends',
            query: makeTrendsQuery(),
            expectedPresent: ['Filters'],
            expectedAbsent: ['Lifecycle Toggles', 'Retention condition', 'Event Types', 'Starts at'],
        },
        {
            name: 'lifecycle',
            query: makeLifecycleQuery(),
            expectedPresent: ['Lifecycle Toggles', 'Filters'],
            expectedAbsent: ['Retention condition', 'Event Types', 'Stickiness Criteria'],
        },
        {
            name: 'stickiness',
            query: makeStickinessQuery(),
            expectedPresent: ['Stickiness Criteria', 'Filters'],
            expectedAbsent: ['Lifecycle Toggles', 'Retention condition', 'Event Types'],
        },
        {
            name: 'retention',
            query: makeRetentionQuery(),
            expectedPresent: ['Retention condition', 'Calculation options', 'Filters'],
            expectedAbsent: ['Lifecycle Toggles', 'Stickiness Criteria', 'Event Types'],
        },
        {
            name: 'funnels',
            query: makeFunnelsQuery(),
            expectedPresent: ['Filters', 'Advanced options'],
            expectedAbsent: ['Lifecycle Toggles', 'Retention condition', 'Event Types'],
        },
        {
            name: 'paths',
            query: makePathsQuery(),
            expectedPresent: ['Event Types', 'Starts at', 'Filters'],
            expectedAbsent: ['Lifecycle Toggles', 'Retention condition', 'Stickiness Criteria'],
        },
    ])('$name shows correct filter labels', ({ query, expectedPresent, expectedAbsent }) => {
        setupAndRender(query)
        for (const text of expectedPresent) {
            expect(screen.getByText(text)).toBeInTheDocument()
        }
        for (const text of expectedAbsent) {
            expect(screen.queryByText(text)).not.toBeInTheDocument()
        }
    })

    it('hides formula mode toggle for trends', () => {
        setupAndRender(makeTrendsQuery())
        expect(screen.queryByText('Enable formula mode')).not.toBeInTheDocument()
    })

    it('expands advanced options section on click', async () => {
        setupAndRender(makeFunnelsQuery())

        const advancedButton = screen.getByRole('button', { name: /Advanced options/ })
        expect(advancedButton).toHaveAttribute('title', 'Show more')

        await userEvent.click(advancedButton)
        expect(advancedButton).toHaveAttribute('title', 'Show less')
        expect(screen.getByText('Use person properties from query time')).toBeInTheDocument()
    })

    it('disables query-time person properties for data warehouse insights', async () => {
        setupAndRender(makeDataWarehouseTrendsQuery())

        await userEvent.click(screen.getByRole('button', { name: /Advanced options/ }))

        const disabledArea = screen.getByText('Use person properties from query time').closest('.LemonDisabledArea')
        expect(disabledArea).toHaveAttribute('aria-disabled', 'true')

        await userEvent.hover(disabledArea as HTMLElement)

        expect(
            await screen.findByText('Data warehouse insights always use the latest table properties.')
        ).toBeInTheDocument()
        expect(within(disabledArea as HTMLElement).getByRole('switch')).toBeDisabled()
    })

    it('shows funnel settings collapsed by default and expandable', async () => {
        setupAndRender(makeFunnelsQuery())

        const settingsButton = screen.getByRole('button', { name: /Funnel settings/ })
        expect(settingsButton).toBeInTheDocument()
        expect(settingsButton).toHaveAttribute('title', 'Show more')

        await userEvent.click(settingsButton)
        expect(settingsButton).toHaveAttribute('title', 'Show less')
    })
})
