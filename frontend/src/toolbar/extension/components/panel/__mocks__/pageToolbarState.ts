import { DEFAULT_HEATMAP_FILTERS } from 'lib/components/IframedToolbarBrowser/utils'

import type { FlagComparison } from '~/toolbar/shared/flags/flagComparisonLogic'
import type { ActionForm } from '~/toolbar/shared/types'

import type { PageToolbarMode, PageToolbarState } from '../../../messaging/pageToolbarBridge'

export const STORY_PAGE_URL = 'https://hedgebox.example.com/pricing'

export function pageToolbarState(mode: PageToolbarMode): PageToolbarState {
    return {
        mode,
        inspect: {
            element: {
                tagName: 'button',
                actionStep: {
                    event: '$autocapture',
                    tag_name: 'button',
                    text: 'Start free trial',
                    selector: '[data-attr="pricing-start-trial"]',
                    href: null,
                    url: STORY_PAGE_URL,
                },
                stats: { count: 412, clickCount: 398, rageclickCount: 9, deadclickCount: 5, rank: 1 },
                actions: [{ id: 2, name: 'Started trial' }],
            },
            isSelected: true,
        },
        selectorCounts: {},
        heatmap: {
            wildcardHref: STORY_PAGE_URL,
            autoWildcardEnabled: false,
            wildcardHrefTooSpecific: false,
            wildcardHrefEndsWithSlash: false,
            commonFilters: { date_from: '-7d' },
            heatmapFilters: DEFAULT_HEATMAP_FILTERS,
            heatmapColorPalette: 'default',
            heatmapFixedPositionMode: 'fixed',
            viewportRange: { min: 1152, max: 1408 },
            rawHeatmapLoading: false,
            variantFilter: null,
            variantFlags: [
                {
                    flagKey: 'pricing-page-redesign',
                    variants: [
                        { flagKey: 'pricing-page-redesign', variant: 'control' },
                        { flagKey: 'pricing-page-redesign', variant: 'test' },
                    ],
                },
            ],
            variantFilterGate: true,
            heatmapsCollection: 'enabled',
            scrollDepthPosthogJsError: null,
            clickmapsEnabled: true,
            clickmapLoading: false,
            processingProgress: null,
            matchLinksByHref: true,
            countedElements: [
                { text: 'Start free trial', tagName: 'button', count: 398 },
                { text: 'Compare plans', tagName: 'a', count: 211 },
                { text: 'Contact sales', tagName: 'a', count: 87 },
            ],
            clickCount: 696,
            canLoadMoreElementStats: false,
            loadedElementStatsCount: 3,
            loadingAllElementStats: false,
            areaSelectionActive: false,
            areaFilter: null,
            savingHeatmap: false,
            saveProgress: null,
            saveResult: null,
        },
        actions: {
            allActionsLoading: false,
            actions: [
                { id: 1, name: 'Viewed pricing' },
                { id: 2, name: 'Started trial' },
                { id: 3, name: 'Clicked contact sales' },
            ],
            selectedActionId: null,
            actionForm: { name: null, steps: [{}] } as ActionForm,
            formRevision: 0,
            actionFormElementsChains: {},
            inspectingElement: null,
            saving: false,
            saveResult: null,
        },
        flags: {
            available: true,
            loading: false,
            flags: [
                {
                    key: 'new-pricing-page',
                    id: 11,
                    value: true,
                    currentValue: true,
                    hasOverride: false,
                    variants: [],
                    payloadOverride: undefined,
                },
                {
                    key: 'checkout-button-copy',
                    id: 12,
                    value: 'control',
                    currentValue: 'test',
                    hasOverride: true,
                    variants: [
                        { key: 'control', name: 'Control', rolloutPercentage: 50 },
                        { key: 'test', name: 'Test', rolloutPercentage: 50 },
                    ],
                    payloadOverride: undefined,
                },
                {
                    key: 'annual-billing-toggle',
                    id: 13,
                    value: false,
                    currentValue: false,
                    hasOverride: false,
                    variants: [],
                    payloadOverride: undefined,
                },
            ],
            countFlagsOverridden: 1,
            impersonatedDistinctId: null,
            payloadErrors: {},
            mutationPending: false,
            mutationError: null,
            mutationRevision: 0,
            comparingFlagKey: null,
            comparisonError: null,
        },
        events: {
            available: true,
            selectedEventTypes: ['posthog', 'custom'],
            hidePostHogProperties: false,
            hidePostHogFlags: false,
            relativeTimestamps: false,
            isPaused: false,
            bufferedCount: 0,
            totalCount: 4,
            filteredCount: 4,
            countsByType: { posthog: 3, custom: 1, snapshot: 0 },
            rows: [
                { uuid: 'event-4', event: 'trial started', timestamp: '2026-01-15T10:00:42.000Z', pinned: false },
                { uuid: 'event-3', event: '$autocapture', timestamp: '2026-01-15T10:00:41.000Z', pinned: false },
                { uuid: 'event-2', event: '$web_vitals', timestamp: '2026-01-15T10:00:03.000Z', pinned: false },
                { uuid: 'event-1', event: '$pageview', timestamp: '2026-01-15T10:00:00.000Z', pinned: false },
            ],
            expandedEventId: null,
            expandedProperties: {},
            expandedEventPayload: null,
        },
        webVitals: {
            autocaptureEnabled: true,
            pathname: '/pricing',
            localWebVitals: { FCP: 812, LCP: 1640, INP: 96, CLS: 0.04 },
            remoteWebVitals: { FCP: 1210, LCP: 2380, INP: 180, CLS: 0.08 },
        },
        experiments: {
            loading: false,
            experiments: [
                { id: 21, name: 'Pricing headline' },
                { id: 22, name: 'Trial button color' },
            ],
            webExperimentsDisabled: false,
            selectedExperimentId: null,
            experimentForm: { name: '', variants: {} },
            formRevision: 0,
            selectedVariant: '',
            selectedElementType: 'all-elements',
            inspectingElement: null,
            addVariantAvailable: true,
            removeVariantAvailable: false,
            saving: false,
            saveResult: null,
        },
        more: {
            debugInfo: {
                version: '1.300.0',
                apiHost: 'https://us.i.posthog.com',
                uiHost: null,
                autocapture: true,
                rageclicks: true,
                deadClicks: true,
                heatmaps: true,
                sessionRecordingStarted: true,
                sessionRecordingStatus: 'active',
                sessionReplayUrl: 'https://us.posthog.com/project/1/replay/session-1',
                surveysCount: 2,
            },
            debugInfoLoading: false,
            piiMaskingEnabled: false,
            piiMaskingColor: '#cccccc',
            piiWarnings: [],
            screenshot: {
                taking: false,
                open: false,
                eventName: '',
                suggestions: [],
                suggestionsLoading: false,
                selectedEventId: null,
                uploading: false,
                result: null,
            },
        },
    }
}

function pricingPageImage(buttonColor: string, buttonText: string): string {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#fff"/><rect x="40" y="40" width="560" height="40" fill="#e5e7eb"/><text x="40" y="150" font-family="sans-serif" font-size="32" fill="#111">Pricing</text><rect x="40" y="200" width="260" height="56" rx="6" fill="${buttonColor}"/><text x="60" y="236" font-family="sans-serif" font-size="20" fill="#fff">${buttonText}</text></svg>`
    return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

export const flagComparison: FlagComparison = {
    flagKey: 'checkout-button-copy',
    identical: false,
    captures: [
        {
            value: false,
            label: 'Off',
            url: pricingPageImage('#1d4ed8', 'Start free trial'),
            width: 640,
            height: 480,
            sameAsOff: true,
        },
        {
            value: 'control',
            label: 'control',
            url: pricingPageImage('#15803d', 'Start free trial'),
            width: 640,
            height: 480,
            sameAsOff: false,
        },
        {
            value: 'test',
            label: 'test',
            url: pricingPageImage('#15803d', 'Try it free'),
            width: 640,
            height: 480,
            sameAsOff: false,
        },
    ],
}
