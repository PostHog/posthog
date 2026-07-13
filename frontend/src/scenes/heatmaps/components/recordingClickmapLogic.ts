import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import { collectAllElementsDeep } from 'query-selector-shadow-dom'
import { RefObject } from 'react'

import api from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { buildDOMIndex, matchEventToElementUsingIndex } from '~/toolbar/elements/domElementIndex'
import { escapeUnescapedRegex } from '~/toolbar/elements/heatmapToolbarMenuLogic'
import { ElementsEventType } from '~/toolbar/types'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getElementsStatsRetrieveUrl } from 'products/product_analytics/frontend/generated/api'
import type {
    ElementStatsResponseApi,
    ElementsStatsRetrieveParams,
} from 'products/product_analytics/frontend/generated/api.schemas'

import { heatmapsBrowserLogic, isUrlPattern } from './heatmapsBrowserLogic'
import type { recordingClickmapLogicType } from './recordingClickmapLogicType'

export interface ClickmapBox {
    top: number
    left: number
    width: number
    height: number
    count: number
    clickCount: number
    rageclickCount: number
    deadclickCount: number
    label: string
    displaySelector: string
}

export type RecordingClickmapLogicProps = {
    iframeRef?: RefObject<HTMLIFrameElement | null>
}

const CLICKMAP_STATS_LIMIT = 500

function currentUrlProperty(href: string, isPattern: boolean): Record<string, unknown> {
    return isPattern
        ? {
              key: '$current_url',
              value: `^${href.split('*').map(escapeUnescapedRegex).join('.*')}$`,
              operator: PropertyOperator.Regex,
              type: PropertyFilterType.Event,
          }
        : {
              key: '$current_url',
              value: href,
              operator: PropertyOperator.Exact,
              type: PropertyFilterType.Event,
          }
}

export function buildElementStatsParams(
    href: string,
    isPattern: boolean,
    commonFilters: {
        date_from?: string | null
        date_to?: string | null
        filter_test_accounts?: boolean
        cohort_ids?: number[]
    },
    dataAttributes: string[]
): ElementsStatsRetrieveParams {
    const properties: Record<string, unknown>[] = [currentUrlProperty(href, isPattern)]
    for (const cohortId of commonFilters.cohort_ids ?? []) {
        properties.push({
            type: PropertyFilterType.Cohort,
            key: 'id',
            value: cohortId,
            operator: PropertyOperator.In,
        })
    }
    // properties and filter_test_accounts are parsed by the endpoint but missing from its
    // generated schema, hence the widening cast - see the stats action in posthog/api/element.py
    return {
        properties: JSON.stringify(properties),
        date_from: commonFilters.date_from,
        date_to: commonFilters.date_to,
        filter_test_accounts: commonFilters.filter_test_accounts,
        limit: CLICKMAP_STATS_LIMIT,
        data_attributes: dataAttributes.join(','),
    } as unknown as ElementsStatsRetrieveParams
}

function emptyCounts(): Pick<ClickmapBox, 'count' | 'clickCount' | 'rageclickCount' | 'deadclickCount'> {
    return { count: 0, clickCount: 0, rageclickCount: 0, deadclickCount: 0 }
}

function describeElement(element: HTMLElement): { label: string; displaySelector: string } {
    const tag = element.tagName.toLowerCase()
    const id = element.id ? `#${element.id}` : ''
    const firstClass = element.classList.length ? `.${element.classList[0]}` : ''
    return {
        displaySelector: `${tag}${id}${firstClass}`,
        label: element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 60) ?? '',
    }
}

export function computeClickmapBoxes(
    statsRows: ElementStatsResponseApi['results'],
    snapshotDocument: Document,
    snapshotWindow: { scrollX: number; scrollY: number } | null,
    dataAttributes: string[],
    matchLinksByHref: boolean = false
): ClickmapBox[] {
    const pageElements = collectAllElementsDeep('*', snapshotDocument) as HTMLElement[]
    const domIndex = buildDOMIndex(pageElements)
    const countsByElement = new Map<HTMLElement, ReturnType<typeof emptyCounts>>()
    for (const row of statsRows) {
        const match = matchEventToElementUsingIndex(
            row as unknown as ElementsEventType,
            dataAttributes,
            matchLinksByHref,
            domIndex
        )
        if (match) {
            const counts = countsByElement.get(match.element) ?? emptyCounts()
            counts.count += row.count
            if (row.type === '$rageclick') {
                counts.rageclickCount += row.count
            } else if (row.type === '$dead_click') {
                counts.deadclickCount += row.count
            } else {
                counts.clickCount += row.count
            }
            countsByElement.set(match.element, counts)
        }
    }

    const scrollX = snapshotWindow?.scrollX ?? 0
    const scrollY = snapshotWindow?.scrollY ?? 0
    const boxes: ClickmapBox[] = []
    countsByElement.forEach((counts, element) => {
        const rect = element.getBoundingClientRect()
        if (rect.width > 0 && rect.height > 0) {
            boxes.push({
                top: rect.top + scrollY,
                left: rect.left + scrollX,
                width: rect.width,
                height: rect.height,
                ...counts,
                ...describeElement(element),
            })
        }
    })
    return boxes.sort((a, b) => b.count - a.count)
}

export const recordingClickmapLogic = kea<recordingClickmapLogicType>([
    path(['scenes', 'heatmaps', 'components', 'recordingClickmapLogic']),
    props({} as RecordingClickmapLogicProps),
    connect(() => ({
        values: [
            heatmapDataLogic({ context: 'in-app' }),
            ['commonFilters'],
            heatmapsBrowserLogic,
            ['replayIframeData'],
            teamLogic,
            ['currentTeam'],
            projectLogic,
            ['currentProjectId'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            heatmapsBrowserLogic,
            ['onIframeLoad', 'setReplayIframeData', 'setReplayIframeDataURL'],
            heatmapDataLogic({ context: 'in-app' }),
            ['setCommonFilters', 'setWindowWidthOverride', 'setHeatmapTooltipSuppressed'],
        ],
    })),
    actions({
        setClickmapEnabled: (enabled: boolean) => ({ enabled }),
        setMatchLinksByHref: (matchLinksByHref: boolean) => ({ matchLinksByHref }),
        selectClickmapBox: (key: string | null) => ({ key }),
        setHoveredBoxKey: (key: string | null) => ({ key }),
        loadElementStats: true,
        maybeLoadElementStats: true,
        recomputeClickmap: true,
        setClickmapBoxes: (boxes: ClickmapBox[]) => ({ boxes }),
    }),
    reducers({
        clickmapEnabled: [
            true,
            {
                setClickmapEnabled: (_, { enabled }) => enabled,
            },
        ],
        matchLinksByHref: [
            false,
            {
                setMatchLinksByHref: (_, { matchLinksByHref }) => matchLinksByHref,
            },
        ],
        clickmapBoxes: [
            [] as ClickmapBox[],
            {
                setClickmapBoxes: (_, { boxes }) => boxes,
                setClickmapEnabled: (state, { enabled }) => (enabled ? state : []),
                setReplayIframeData: () => [],
                setReplayIframeDataURL: () => [],
            },
        ],
        selectedBoxKey: [
            null as string | null,
            {
                selectClickmapBox: (_, { key }) => key,
                setClickmapBoxes: () => null,
                setClickmapEnabled: () => null,
                setReplayIframeData: () => null,
                setReplayIframeDataURL: () => null,
            },
        ],
        hoveredBoxKey: [
            null as string | null,
            {
                setHoveredBoxKey: (_, { key }) => key,
                setClickmapBoxes: () => null,
                setClickmapEnabled: () => null,
                setReplayIframeData: () => null,
                setReplayIframeDataURL: () => null,
            },
        ],
        // the loader keeps stale stats across recording changes otherwise, and
        // onIframeLoad would repaint the old recording's counts onto the new snapshot
        elementStats: {
            setReplayIframeData: () => null,
            setReplayIframeDataURL: () => null,
        },
    }),
    loaders(({ values }) => ({
        elementStats: [
            null as ElementStatsResponseApi | null,
            {
                loadElementStats: async (_, breakpoint) => {
                    await breakpoint(150)
                    // heatmapDataLogic's href gets clobbered to '' by onIframeLoad in this scene,
                    // so the replay payload's URL is the stable source of truth here
                    const url = values.replayIframeData?.url?.trim()
                    if (!url) {
                        return null
                    }
                    const params = buildElementStatsParams(
                        url,
                        isUrlPattern(url),
                        values.commonFilters,
                        values.wantedDataAttributes
                    )
                    const response = await api.get<ElementStatsResponseApi>(
                        getElementsStatsRetrieveUrl(String(values.currentProjectId), params)
                    )
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    selectors({
        clickmapAvailable: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.HEATMAPS_RECORDING_CLICKMAP],
        ],
        clickmapActive: [
            (s) => [s.clickmapAvailable, s.clickmapEnabled],
            (clickmapAvailable, clickmapEnabled): boolean => clickmapAvailable && clickmapEnabled,
        ],
        wantedDataAttributes: [
            (s) => [s.currentTeam],
            (currentTeam): string[] => Array.from(new Set(['data-attr', ...(currentTeam?.data_attributes ?? [])])),
        ],
        highestClickCount: [
            (s) => [s.clickmapBoxes],
            (clickmapBoxes) => clickmapBoxes.reduce((max, box) => Math.max(max, box.count), 0),
        ],
        totalClickCount: [
            (s) => [s.clickmapBoxes],
            (clickmapBoxes) => clickmapBoxes.reduce((sum, box) => sum + box.count, 0),
        ],
        tooltipSuppressed: [
            (s) => [s.hoveredBoxKey, s.selectedBoxKey],
            (hoveredBoxKey, selectedBoxKey): boolean => hoveredBoxKey !== null || selectedBoxKey !== null,
        ],
    }),
    subscriptions(({ actions }) => ({
        tooltipSuppressed: (value: boolean) => {
            actions.setHeatmapTooltipSuppressed(value)
        },
    })),
    events(({ actions }) => ({
        beforeUnmount: () => {
            // heatmapDataLogic outlives this logic, so its reducer won't reset on our unmount —
            // we must explicitly clear the suppression flag we set via the subscription above
            actions.setHeatmapTooltipSuppressed(false)
        },
    })),
    listeners(({ actions, values, props }) => ({
        setClickmapEnabled: ({ enabled }) => {
            posthog.capture('in-app heatmap clickmap toggled', { enabled })
            if (enabled) {
                actions.maybeLoadElementStats()
            }
        },
        maybeLoadElementStats: () => {
            if (values.clickmapActive && values.replayIframeData?.url?.trim()) {
                actions.loadElementStats()
            }
        },
        setReplayIframeData: () => actions.maybeLoadElementStats(),
        setReplayIframeDataURL: () => actions.maybeLoadElementStats(),
        setCommonFilters: () => actions.maybeLoadElementStats(),
        setMatchLinksByHref: () => actions.recomputeClickmap(),
        setWindowWidthOverride: () => actions.recomputeClickmap(),
        onIframeLoad: () => {
            if (values.elementStats) {
                actions.recomputeClickmap()
            } else {
                actions.maybeLoadElementStats()
            }
        },
        loadElementStatsSuccess: () => actions.recomputeClickmap(),
        recomputeClickmap: async (_, breakpoint) => {
            if (!values.clickmapActive || !values.replayIframeData?.url?.trim()) {
                return
            }
            await breakpoint(50)
            const iframe = props.iframeRef?.current
            const snapshotDocument = iframe?.contentDocument
            const statsRows = values.elementStats?.results
            if (!snapshotDocument?.body || !statsRows?.length) {
                actions.setClickmapBoxes([])
                return
            }

            const boxes = computeClickmapBoxes(
                statsRows,
                snapshotDocument,
                iframe?.contentWindow ?? null,
                values.wantedDataAttributes,
                values.matchLinksByHref
            )
            posthog.capture('in-app heatmap clickmap rendered', {
                stats_rows: statsRows.length,
                matched_elements: boxes.length,
                has_more: !!values.elementStats?.next,
            })
            actions.setClickmapBoxes(boxes)
        },
    })),
])
