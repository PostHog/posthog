import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, RetentionQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    AnyPropertyFilter,
    InsightLogicProps,
    InsightModel,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
} from '~/types'

import { retentionLogic } from './retentionLogic'

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

const browserFilter: AnyPropertyFilter = {
    key: '$browser',
    value: ['Chrome'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

const cohortRow = (date: string, counts: number[]): Record<string, any> => ({
    date,
    label: 'Day 0',
    values: counts.map((count) => ({ count })),
})

const retentionQuery = ({
    targetProperties,
    returningProperties,
}: {
    targetProperties?: AnyPropertyFilter[]
    returningProperties?: AnyPropertyFilter[]
} = {}): RetentionQuery => ({
    kind: NodeKind.RetentionQuery,
    retentionFilter: {
        period: RetentionPeriod.Day,
        targetEntity: { id: '$pageview', type: 'events', properties: targetProperties },
        returningEntity: { id: '$pageview', type: 'events', properties: returningProperties },
    },
})

let logic: ReturnType<typeof retentionLogic.build>

describe('retentionLogic', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': { count: 0, results: [] },
                '/api/environments/:team_id/data_color_themes/': [],
            },
        })
        initKeaTests(false)
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()

        dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode }).mount()

        logic = retentionLogic(insightProps)
        logic.mount()
    })

    async function loadResults(query: RetentionQuery, result: Record<string, any>[]): Promise<void> {
        await expectLogic(logic, () => {
            logic.actions.updateQuerySource(query)
            // Rebuilding with the query as props mirrors how InsightViz passes the source query
            // down; retentionLogic.results gates on it. cachedResults set the response without
            // a network round-trip.
            dataNodeLogic({
                key: 'InsightViz.new',
                query: query as DataNode,
                cachedResults: { result } as Partial<InsightModel>,
            })
        }).toFinishAllListeners()
    }

    // These two selectors gate RetentionEmptyResultsBanner: a regression in either silently
    // removes the explanation shown when property filters empty out every cohort.
    it.each([
        {
            name: 'all-zero cohorts with a target entity property filter',
            query: retentionQuery({ targetProperties: [browserFilter] }),
            rows: [cohortRow('2024-01-01T00:00:00Z', [0, 0]), cohortRow('2024-01-02T00:00:00Z', [0, 0])],
            allCohortsEmpty: true,
            hasEntityPropertyFilters: true,
        },
        {
            name: 'a non-empty cohort with a target entity property filter',
            query: retentionQuery({ targetProperties: [browserFilter] }),
            rows: [cohortRow('2024-01-01T00:00:00Z', [100, 50]), cohortRow('2024-01-02T00:00:00Z', [0, 0])],
            allCohortsEmpty: false,
            hasEntityPropertyFilters: true,
        },
        {
            name: 'all-zero cohorts without entity property filters',
            query: retentionQuery(),
            rows: [cohortRow('2024-01-01T00:00:00Z', [0, 0])],
            allCohortsEmpty: true,
            hasEntityPropertyFilters: false,
        },
        {
            name: 'a returning entity property filter only',
            query: retentionQuery({ returningProperties: [browserFilter] }),
            rows: [cohortRow('2024-01-01T00:00:00Z', [0, 0])],
            allCohortsEmpty: true,
            hasEntityPropertyFilters: true,
        },
        {
            name: 'no results',
            query: retentionQuery({ targetProperties: [browserFilter] }),
            rows: [],
            allCohortsEmpty: false,
            hasEntityPropertyFilters: true,
        },
    ])('$name', async ({ query, rows, allCohortsEmpty, hasEntityPropertyFilters }) => {
        await loadResults(query, rows)

        expect(logic.values.allCohortsEmpty).toBe(allCohortsEmpty)
        expect(logic.values.hasEntityPropertyFilters).toBe(hasEntityPropertyFilters)
    })
})
