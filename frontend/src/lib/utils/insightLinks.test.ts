import { getInsightDefinitionUrl } from 'lib/utils/insightLinks'

import { NodeKind } from '~/queries/schema/schema-general'

describe('getInsightDefinitionUrl', () => {
    it('generates a template link for an unsaved insight (raw query)', () => {
        const query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: null,
                        name: 'All events',
                        math: 'total',
                    },
                ],
                trendsFilter: {},
            },
        }
        const url = getInsightDefinitionUrl({ query }, 'https://app.posthog.com')
        expect(url).toMatch(/^https:\/\/app\.posthog\.com\/insights\/new#insight=TRENDS&q=%7B.*%7D(%20)?$/)
        // Should not include /project/<id>
        expect(url).not.toContain('/project/')
    })

    it('generates a template link for a saved insight (model)', () => {
        interface MinimalInsight {
            query: any
            id: number
            name: string
        }
        const savedInsight: MinimalInsight = {
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [],
                    funnelsFilter: {},
                },
            },
            id: 123,
            name: 'My Funnel',
        }
        const url = getInsightDefinitionUrl(savedInsight, 'https://app.posthog.com')
        expect(url).toMatch(/^https:\/\/app\.posthog\.com\/insights\/new#insight=FUNNELS&q=%7B.*%7D(%20)?$/)
        expect(url).not.toContain('/project/')
    })
})
