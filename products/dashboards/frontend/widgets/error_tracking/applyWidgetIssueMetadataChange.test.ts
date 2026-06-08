import type { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { errorTrackingSampleIssues } from '../../components/WidgetCard/widgetOverviewStoryFixtures'
import { applyIssueMetadataToWidgetListResult } from './applyWidgetIssueMetadataChange'

describe('applyIssueMetadataToWidgetListResult', () => {
    const baseResult = {
        results: errorTrackingSampleIssues.slice(0, 2).map((issue, index) => ({
            ...issue,
            id: index === 0 ? 'a' : 'b',
            name: index === 0 ? 'Error A' : 'Error B',
        })) as ErrorTrackingIssue[],
        hasMore: false,
    }

    it('updates assignee in place', () => {
        const assignee = { type: 'user' as const, id: 7 }
        const next = applyIssueMetadataToWidgetListResult(baseResult, 'a', { assignee }, { statusFilter: 'active' })
        expect(next.results?.[0]?.assignee).toEqual(assignee)
        expect(next.results?.[1]?.assignee).toBeNull()
    })

    it('removes the issue when status no longer matches the tile filter', () => {
        const next = applyIssueMetadataToWidgetListResult(
            { ...baseResult, totalCount: 2 },
            'a',
            { status: 'resolved' },
            { statusFilter: 'active' }
        )
        expect(next.results).toHaveLength(1)
        expect(next.results?.[0]?.id).toBe('b')
        expect(next.totalCount).toBe(1)
    })

    it('keeps resolved issues when tile filter is all', () => {
        const next = applyIssueMetadataToWidgetListResult(
            baseResult,
            'a',
            { status: 'resolved' },
            { statusFilter: 'all' }
        )
        expect(next.results?.[0]?.status).toBe('resolved')
    })

    it('removes the issue when assignee no longer matches the tile filter', () => {
        const next = applyIssueMetadataToWidgetListResult(
            {
                ...baseResult,
                results: [
                    {
                        ...errorTrackingSampleIssues[0],
                        id: 'a',
                        status: 'active',
                        assignee: { type: 'user', id: 1 },
                        name: 'Error A',
                    } as ErrorTrackingIssue,
                ],
            },
            'a',
            { assignee: { type: 'user', id: 2 } },
            { statusFilter: 'active', assigneeFilter: { type: 'user', id: 1 } }
        )
        expect(next.results).toEqual([])
    })
})
