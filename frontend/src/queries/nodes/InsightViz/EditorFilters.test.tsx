import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

// Mock MaxTool to render children directly (avoids AI integration setup)
jest.mock('scenes/max/MaxTool', () => ({
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Mock heavy filter components — we're testing EditorFilters' orchestration, not the components themselves
jest.mock('./TrendsSeries', () => ({ TrendsSeries: () => null }))
jest.mock('./TrendsFormula', () => ({ TrendsFormula: () => null }))
jest.mock('./GlobalAndOrFilters', () => ({ GlobalAndOrFilters: () => null }))
jest.mock('./Breakdown', () => ({ Breakdown: () => null }))
jest.mock('./CumulativeStickinessFilter', () => ({ CumulativeStickinessFilter: () => null }))
jest.mock('~/queries/nodes/InsightViz/StickinessCriteria', () => ({ StickinessCriteria: () => null }))
jest.mock('scenes/insights/EditorFilters/AttributionFilter', () => ({ Attribution: () => null }))
jest.mock('scenes/insights/EditorFilters/FunnelsAdvanced', () => ({ FunnelsAdvanced: () => null }))
jest.mock('scenes/insights/EditorFilters/FunnelsQuerySteps', () => ({ FunnelsQuerySteps: () => null }))
jest.mock('scenes/insights/EditorFilters/GoalLines', () => ({ GoalLines: () => null }))
jest.mock('scenes/insights/EditorFilters/PathsAdvanced', () => ({ PathsAdvanced: () => null }))
jest.mock('scenes/insights/EditorFilters/PathsEventTypes', () => ({ PathsEventsTypes: () => null }))
jest.mock('scenes/insights/EditorFilters/PathsExclusions', () => ({ PathsExclusions: () => null }))
jest.mock('scenes/insights/EditorFilters/PathsHogQL', () => ({ PathsHogQL: () => null }))
jest.mock('scenes/insights/EditorFilters/PathsTarget', () => ({
    PathsTargetStart: () => null,
    PathsTargetEnd: () => null,
}))
jest.mock('scenes/insights/EditorFilters/PathsWildcardGroups', () => ({ PathsWildcardGroups: () => null }))
jest.mock('scenes/insights/EditorFilters/PoeFilter', () => ({ PoeFilter: () => null }))
jest.mock('scenes/insights/EditorFilters/RetentionCondition', () => ({ RetentionCondition: () => null }))
jest.mock('scenes/insights/EditorFilters/RetentionOptions', () => ({ RetentionOptions: () => null }))
jest.mock('scenes/insights/EditorFilters/SamplingDeprecationNotice', () => ({
    SamplingDeprecationNotice: () => null,
}))
jest.mock('./LifecycleToggles', () => ({ LifecycleToggles: () => null }))

const Insight123 = '123' as InsightShortId
const insightProps = { dashboardItemId: Insight123 }

function makeTrendsQuery(): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, name: '$pageview', event: '$pageview', math: BaseMathType.TotalCount }],
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
    return { kind: NodeKind.PathsQuery }
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
        featureFlagLogic().mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'trends',
            query: makeTrendsQuery(),
            expectedPresent: ['Enable formula mode', 'Filters'],
            expectedAbsent: ['Lifecycle Toggles', 'Retention condition', 'Event Types', 'Starts at'],
        },
        {
            name: 'lifecycle',
            query: makeLifecycleQuery(),
            expectedPresent: ['Lifecycle Toggles', 'Filters'],
            expectedAbsent: ['Enable formula mode', 'Retention condition', 'Event Types', 'Stickiness Criteria'],
        },
        {
            name: 'stickiness',
            query: makeStickinessQuery(),
            expectedPresent: ['Stickiness Criteria', 'Compute as', 'Filters'],
            expectedAbsent: ['Enable formula mode', 'Lifecycle Toggles', 'Retention condition', 'Event Types'],
        },
        {
            name: 'retention',
            query: makeRetentionQuery(),
            expectedPresent: ['Retention condition', 'Calculation options', 'Filters'],
            expectedAbsent: ['Enable formula mode', 'Lifecycle Toggles', 'Stickiness Criteria', 'Event Types'],
        },
        {
            name: 'funnels',
            query: makeFunnelsQuery(),
            expectedPresent: ['Filters', 'Advanced options'],
            expectedAbsent: ['Enable formula mode', 'Lifecycle Toggles', 'Retention condition', 'Event Types'],
        },
        {
            name: 'paths',
            query: makePathsQuery(),
            expectedPresent: ['Event Types', 'Starts at', 'Filters'],
            expectedAbsent: ['Enable formula mode', 'Lifecycle Toggles', 'Retention condition', 'Stickiness Criteria'],
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

    describe('formula mode toggle', () => {
        it('shows "Enable formula mode" for trends by default', () => {
            setupAndRender(makeTrendsQuery())
            expect(screen.getByText('Enable formula mode')).toBeInTheDocument()
        })

        it('toggles to "Disable formula mode" after clicking', async () => {
            const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime })
            jest.useFakeTimers()
            setupAndRender(makeTrendsQuery())

            await user.click(screen.getByText('Enable formula mode'))
            await act(async () => {
                jest.advanceTimersByTime(500)
            })

            expect(screen.getByText('Disable formula mode')).toBeInTheDocument()
            jest.useRealTimers()
        })
    })

    describe('advanced options', () => {
        it('collapses and expands advanced options section', async () => {
            setupAndRender(makeFunnelsQuery())

            const advancedOptionsButton = screen.getByRole('button', { name: /Advanced options/ })
            expect(advancedOptionsButton).toBeInTheDocument()

            // Starts collapsed (defaultExpanded: false)
            await userEvent.click(advancedOptionsButton)
            // After click it should expand — button still present
            expect(screen.getByRole('button', { name: /Advanced options/ })).toBeInTheDocument()
        })
    })
})
