import { dayjs } from 'lib/dayjs'
import { SummaryContext } from 'scenes/insights/summarizeInsight'

import { Node, NodeKind } from '~/queries/schema/schema-general'
import { SavedInsightsTabs, UserType } from '~/types'

import { DraftInsightQuery, draftInsightMatchesFilters } from './draftInsight'
import { SavedInsightFilters, cleanFilters } from './savedInsightsLogic'

describe('draftInsightMatchesFilters', () => {
    const user = { id: 7 } as UserType
    const summaryContext: SummaryContext = {
        aggregationLabel: () => ({ singular: 'user', plural: 'users' }),
        cohortsById: {},
        mathDefinitions: {},
    }

    const trendsDraft: DraftInsightQuery = {
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: 'total' }],
            },
        } as Node<Record<string, any>>,
        timestamp: Date.now(),
    }
    const sqlDraft: DraftInsightQuery = {
        query: {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
        } as Node<Record<string, any>>,
        timestamp: Date.now(),
    }
    const eventsTableDraft: DraftInsightQuery = {
        query: {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.EventsQuery, select: ['*'] },
        } as Node<Record<string, any>>,
        timestamp: Date.now(),
    }
    const oldTrendsDraft: DraftInsightQuery = { ...trendsDraft, timestamp: dayjs().subtract(30, 'day').valueOf() }

    it.each<[string, DraftInsightQuery, Partial<SavedInsightFilters>, boolean]>([
        ['no filters', trendsDraft, {}, true],
        ['matching insight type', trendsDraft, { insightType: 'TRENDS' }, true],
        ['non-matching insight type', trendsDraft, { insightType: 'FUNNELS' }, false],
        ['SQL type against a trends draft', trendsDraft, { insightType: 'SQL' }, false],
        ['SQL type against a SQL draft', sqlDraft, { insightType: 'SQL' }, true],
        ['JSON type against a SQL draft', sqlDraft, { insightType: 'JSON' }, false],
        ['JSON type against a trends draft', trendsDraft, { insightType: 'JSON' }, false],
        ['JSON type against an events table draft', eventsTableDraft, { insightType: 'JSON' }, true],
        ['search matching the summarized query', trendsDraft, { search: 'pageview' }, true],
        ['search not matching the summarized query', trendsDraft, { search: 'revenue' }, false],
        ['favorites only', trendsDraft, { favorited: true }, false],
        ['a tag filter', trendsDraft, { tags: ['marketing'] }, false],
        ['created by including the current user', trendsDraft, { createdBy: [7] }, true],
        ['created by excluding the current user', trendsDraft, { createdBy: [999] }, false],
        ['created by ignored on the Yours tab', trendsDraft, { tab: SavedInsightsTabs.Yours, createdBy: [999] }, true],
        ['last modified within range', trendsDraft, { dateFrom: '-7d' }, true],
        ['last modified out of range', oldTrendsDraft, { dateFrom: '-7d' }, false],
        ['created date out of range', oldTrendsDraft, { createdDateFrom: '-7d' }, false],
        ['a last viewed filter (drafts are never viewed)', trendsDraft, { lastViewedDateFrom: '-7d' }, false],
        ['a dashboard filter (drafts are on no dashboard)', trendsDraft, { dashboardId: 5 }, false],
    ])('applies %s', (_label, draft, filterOverrides, expected) => {
        expect(draftInsightMatchesFilters(draft, cleanFilters(filterOverrides), user, summaryContext)).toBe(expected)
    })
})
