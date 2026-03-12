import { StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { useStorybookMocks } from '~/mocks/browser'
import { InsightVizNode, Node } from '~/queries/schema/schema-general'
import { isInsightVizNode, isLifecycleQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'
import { QueryBasedInsightModel } from '~/types'

function setLegendFilter(query: Node | null | undefined, showLegend: boolean): Node | null | undefined {
    if (!isInsightVizNode(query)) {
        return query
    }

    if (isTrendsQuery(query.source)) {
        return {
            ...query,
            source: {
                ...query.source,
                trendsFilter: { ...query.source.trendsFilter, showLegend },
            },
        } as InsightVizNode
    } else if (isLifecycleQuery(query.source)) {
        return {
            ...query,
            source: { ...query.source, lifecycleFilter: { ...query.source.lifecycleFilter, showLegend } },
        } as InsightVizNode
    } else if (isStickinessQuery(query.source)) {
        return {
            ...query,
            source: { ...query.source, stickinessFilter: { ...query.source.stickinessFilter, showLegend } },
        } as InsightVizNode
    }

    return query
}

interface InsightStoryOptions {
    openSidePanel?: boolean
}

let shortCounter = 0
export function createInsightStory(
    insight: Partial<QueryBasedInsightModel>,
    mode: 'view' | 'edit' = 'view',
    showLegend: boolean = false,
    options: InsightStoryOptions = {}
): StoryFn<typeof App> {
    const count = shortCounter++
    return function InsightStory() {
        document.body.classList.add('storybook-test-runner')
        useMountedLogic(sceneLayoutLogic)

        useStorybookMocks({
            get: {
                '/api/environments/:team_id/insights/': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        count: 1,
                        results: [
                            {
                                ...insight,
                                short_id: `${insight.short_id}${count}`,
                                id: (insight.id ?? 0) + 1 + count,
                                query: setLegendFilter(insight.query, showLegend),
                            },
                        ],
                    }),
                ],
            },
            post: {
                '/api/environments/:team_id/query/': (req, __, ctx) => [
                    ctx.status(200),
                    ctx.json({
                        cache_key: req.params.query,
                        calculation_trigger: null,
                        error: '',
                        hasMore: false,
                        is_cached: true,
                        query_status: null,
                        results: insight.result,
                        // sql insights
                        columns: (insight as any).columns,
                        types: (insight as any).types,
                        // trends box plot insight
                        boxplot_data: (insight as any).boxplot_data,
                    }),
                ],
            },
        })

        useOnMountEffect(() => {
            router.actions.push(`/insights/${insight.short_id}${count}${mode === 'edit' ? '/edit' : ''}`)
            if (options.openSidePanel) {
                sceneLayoutLogic.actions.setScenePanelOpen(true)
            }
        })

        return <App />
    }
}
