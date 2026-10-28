import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'

import { BIEditorView, buildBIQuery, parseBIEditorState } from './biEditorTypes'
import { BI_QUESTION_STARTERS, starterWorksheetUrl } from './biQuestionStarters'

it('opens each question as editable shelves with a seven-day window, without a SQL snapshot', () => {
    for (const starter of BI_QUESTION_STARTERS) {
        const url = new URL(starterWorksheetUrl(starter.config), 'https://example.com')
        const worksheet = JSON.parse(new URLSearchParams(url.hash.slice(1)).get('q')!) as BIVisualizationNode
        const restored = parseBIEditorState(BIEditorView.BI, JSON.stringify(worksheet.config))!.config
        expect(url.searchParams.get('starter')).toBe('1')
        expect(restored.querySnapshot).toBeUndefined()
        expect(restored.dateRange?.date_from).toBe('-7d')
        expect(buildBIQuery(restored)?.node.source).toEqual(worksheet.source)
    }
})

it('counts people distinctly and restricts referral counts to page views', () => {
    const people = BI_QUESTION_STARTERS.find(({ id }) => id === 'daily_people')!.config
    const reach = BI_QUESTION_STARTERS.find(({ id }) => id === 'event_reach')!.config
    const referrers = BI_QUESTION_STARTERS.find(({ id }) => id === 'pageview_sources')!.config
    expect(buildBIQuery(people)?.query).toContain('count(DISTINCT person_id)')
    expect(reach.sort?.direction).toBe('desc')
    expect(buildBIQuery(reach)?.query).toContain('count(DISTINCT person_id)')
    expect(referrers.filters).toEqual([expect.objectContaining({ operator: 'equals', value: '$pageview' })])
    expect(buildBIQuery(referrers)?.query).toContain('properties.$referring_domain')
})
