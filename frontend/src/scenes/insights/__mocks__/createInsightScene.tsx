import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { StoryFn } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { InsightVizNode, Node } from '~/queries/schema/schema-general'
import { isInsightVizNode, isLifecycleQuery, isStickinessQuery, isTrendsQuery } from '~/queries/utils'
import { QueryBasedInsightModel } from '~/types'

/** Spread into a `createInsightStory` story's `parameters`, merging `testOptions` for extra keys. */
export const insightSceneStoryParameters = {
    layout: 'fullscreen',
    viewMode: 'story',
    mockDate: '2022-03-11',
    testOptions: {
        snapshotBrowsers: ['chromium' as const],
        viewport: {
            // needs a slightly larger width to push the rendered scene away from the breakpoint boundary
            width: 1300,
            height: 720,
        },
    },
}

/** API mocks the insight scene needs beyond the insight itself (editor taxonomy, persons). */
export const insightSceneMswDecorator = mswDecorator({
    get: {
        '/api/environments/:team_id/persons/retention': sampleRetentionPeopleResponse,
        '/api/environments/:team_id/persons/properties': samplePersonProperties,
        '/api/projects/:team_id/groups_types': [],
    },
    post: {
        '/api/projects/:team_id/cohorts/': { id: 1 },
    },
})

/**
 * Play fn: holds the snapshot until the funnel steps chart has painted and settled.
 *
 * Waits on the painted `canvas[role="img"]` — the chart-ready signal — and requires its height to
 * stay non-zero and unchanged across several samples. A slow CI render can exhaust the timeout; that
 * is fine, so resolve instead of throwing. The runner stabilizes the page again before it snapshots,
 * and its `waitForSelector` still fails hard if the canvas never paints — so swallowing the timeout
 * here smooths timing without dropping coverage.
 */
export const waitForFunnelToStabilize = async ({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> => {
    const REQUIRED_STABLE_SAMPLES = 3
    let lastHeight = -1
    let stableSamples = 0
    try {
        await waitFor(
            () => {
                const chart = canvasElement.querySelector('[data-attr=funnel-steps-bar-chart] canvas[role="img"]')
                const currentHeight = chart ? chart.getBoundingClientRect().height : 0
                stableSamples = currentHeight > 0 && currentHeight === lastHeight ? stableSamples + 1 : 0
                lastHeight = currentHeight
                if (stableSamples < REQUIRED_STABLE_SAMPLES) {
                    throw new Error('funnel canvas height not yet stable')
                }
            },
            { timeout: 15000, interval: 200 }
        )
    } catch {
        // Render still settling — the runner stabilizes the page again before snapshotting.
    }
}

/** Play fn: expands the first funnel step's inline property filters. */
export const expandFirstPropertyFilter = async ({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> => {
    const expandFiltersButton = await waitFor(
        () => {
            const filtersButton = canvasElement.querySelector<HTMLElement>('[data-attr="show-prop-filter-0"]')
            if (!filtersButton) {
                throw new Error('Filters button not yet rendered')
            }
            return filtersButton
        },
        { timeout: 2000 }
    )
    await userEvent.click(expandFiltersButton)
}

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
                '/api/environments/:team_id/insights/': () => [
                    200,
                    {
                        count: 1,
                        results: [
                            {
                                ...insight,
                                short_id: `${insight.short_id}${count}`,
                                id: (insight.id ?? 0) + 1 + count,
                                query: setLegendFilter(insight.query, showLegend),
                            },
                        ],
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': ({ params }) => [
                    200,
                    {
                        cache_key: params.query,
                        calculation_trigger: null,
                        error: '',
                        hasMore: false,
                        is_cached: true,
                        query_status: null,
                        results: insight.result,
                        // sql insights
                        columns: (insight as any).columns,
                        types: (insight as any).types,
                        // funnel steps header reads the total median from this top-level field
                        total_median_conversion_time: (insight as any).total_median_conversion_time,
                    },
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
