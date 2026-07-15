import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import {
    AuthorizedUrlListType,
    authorizedUrlListLogic,
    defaultAuthorizedUrlProperties,
} from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { ReplayIframeData, heatmapsBrowserLogic, isUrlPattern } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { AccessControlLevel, AccessControlResourceType, HeatmapType } from '~/types'

import type { heatmapCreationLogicType } from './heatmapCreationLogicType'
import { HeatmapCreationContext, heatmapLogic } from './heatmapLogic'

export type HeatmapCreationStep = 'page' | 'background' | 'review'
export type HeatmapPageAccess = 'public' | 'login'
export type HeatmapDataCheckTrigger = 'automatic' | 'manual'
export type HeatmapDataCheckOutcome = 'detected' | 'none' | 'error'

export interface HeatmapDataCheckResult {
    url: string
    matchType: 'exact' | 'pattern'
    trigger: HeatmapDataCheckTrigger
    outcome: HeatmapDataCheckOutcome
    count: number | null
}

export interface HeatmapDataCheckPayload {
    url: string | null
    matchType: 'exact' | 'pattern'
    trigger: HeatmapDataCheckTrigger
}

export interface RecordingBackgroundSelection {
    storageKey: string
    matchingRecordingCount: number
}

const STEP_ORDER: HeatmapCreationStep[] = ['page', 'background', 'review']

const authorizedUrlsLogic = authorizedUrlListLogic({
    ...defaultAuthorizedUrlProperties,
    type: AuthorizedUrlListType.TOOLBAR_URLS,
})

export function heatmapUrlPatternToRegex(value: string): string {
    let normalized = value
    if (!normalized.startsWith('^')) {
        normalized = `^${normalized}`
    }
    if (!normalized.endsWith('$')) {
        normalized = `${normalized}$`
    }
    return Array.from(normalized)
        .map((character, index) => (character === '*' && index > 0 && normalized[index - 1] !== '.' ? '.+' : character))
        .join('')
}

export function getPageStepBlockReason({
    displayUrl,
    isDisplayUrlValid,
    dataUrl,
    isDataUrlValid,
}: {
    displayUrl: string | null
    isDisplayUrlValid: boolean
    dataUrl: string | null
    isDataUrlValid: boolean
}): string | null {
    if (!displayUrl?.trim()) {
        return 'Enter a page URL to continue'
    }
    if (!isDisplayUrlValid) {
        return 'Enter a valid page URL to continue'
    }
    if (dataUrl?.trim() && !isDataUrlValid) {
        return 'Enter a valid heatmap data URL to continue'
    }
    return null
}

export function getBackgroundStepBlockReason({
    pageAccess,
    type,
    isDisplayUrlAuthorized,
    hasRecordingBackground,
}: {
    pageAccess: HeatmapPageAccess | null
    type: HeatmapType
    isDisplayUrlAuthorized: boolean
    hasRecordingBackground: boolean
}): string | null {
    if (!pageAccess) {
        return 'Choose whether this page requires login'
    }
    if (pageAccess === 'login') {
        return hasRecordingBackground ? null : 'Choose a session recording moment to continue'
    }
    if (type === 'iframe' && !isDisplayUrlAuthorized) {
        return 'Authorize this URL or choose Screenshot to continue'
    }
    return null
}

export function getStoredRecordingBackground(storageKey: string | null): ReplayIframeData | null {
    if (!storageKey) {
        return null
    }
    try {
        const data = JSON.parse(localStorage.getItem(storageKey) ?? 'null') as Partial<ReplayIframeData> | null
        if (
            !data ||
            typeof data.html !== 'string' ||
            !data.html.trim() ||
            typeof data.width !== 'number' ||
            typeof data.height !== 'number'
        ) {
            return null
        }
        return data as ReplayIframeData
    } catch {
        return null
    }
}

export function getAuthorizationOrigin(url: string | null): string | null {
    if (!url) {
        return null
    }
    try {
        return new URL(url).origin
    } catch {
        return null
    }
}

interface WizardStepValues {
    captureEnabled: boolean
    hasMatchingData: boolean | null
    pageAccess: HeatmapPageAccess | null
    analyticsBackgroundType: HeatmapType | 'recording'
}

function captureWizardStepCompleted(
    values: WizardStepValues,
    step: HeatmapCreationStep,
    overrides: { page_access?: HeatmapPageAccess; background_type?: HeatmapType | 'recording' } = {}
): void {
    posthog.capture('in-app heatmap creation wizard step completed', {
        step,
        capture_enabled: values.captureEnabled,
        has_matching_data: values.hasMatchingData,
        page_access: values.pageAccess,
        background_type: values.analyticsBackgroundType,
        ...overrides,
    })
}

export const heatmapCreationLogic = kea<heatmapCreationLogicType>([
    path(['scenes', 'heatmaps', 'scenes', 'heatmap', 'heatmapCreationLogic']),

    connect(() => ({
        values: [
            heatmapLogic({ id: 'new' }),
            ['dataUrl', 'displayUrl', 'isBrowserUrlValid', 'isDisplayUrlValid', 'loading', 'type'],
            teamLogic,
            ['currentTeam'],
            authorizedUrlsLogic,
            ['checkUrlIsAuthorized'],
            sessionPlayerModalLogic,
            ['modalContext'],
        ],
        actions: [
            heatmapLogic({ id: 'new' }),
            ['creationCompleted', 'setDataUrl', 'setDisplayUrl', 'setType'],
            authorizedUrlsLogic,
            ['addUrl'],
            heatmapsBrowserLogic,
            ['setReplayIframeData'],
            sessionPlayerModalLogic,
            ['completeHeatmapBackgroundSelection'],
        ],
    })),

    actions({
        applyStep: (step: HeatmapCreationStep) => ({ step }),
        navigateToStep: (step: HeatmapCreationStep) => ({ step }),
        continueFromPage: true,
        continueFromBackground: true,
        goBack: true,
        setPageAccess: (pageAccess: HeatmapPageAccess) => ({ pageAccess }),
        resetForPageChange: true,
        requestPageDataCheck: (trigger: HeatmapDataCheckTrigger) => ({ trigger }),
        authorizeDisplayUrl: true,
        markRecordingHandoff: (matchingRecordingCount: number) => ({ matchingRecordingCount }),
        selectRecordingBackground: (storageKey: string, matchingRecordingCount: number) => ({
            storageKey,
            matchingRecordingCount,
        }),
        openRecordingHeatmap: true,
        showRecordingHeatmap: true,
        closeRecordingHeatmap: true,
        finishRecordingHeatmap: true,
    }),

    loaders(({ values }) => ({
        pageDataCheck: [
            null as HeatmapDataCheckResult | null,
            {
                checkPageData: async (
                    payload: HeatmapDataCheckPayload,
                    breakpoint
                ): Promise<HeatmapDataCheckResult | null> => {
                    const { url, matchType, trigger } = payload
                    if (!url) {
                        return null
                    }
                    await breakpoint(trigger === 'automatic' ? 500 : 0)
                    if (url !== values.effectiveDataUrl) {
                        return { url, matchType, trigger, outcome: 'error', count: null }
                    }
                    const query =
                        matchType === 'pattern'
                            ? hogql`SELECT count() FROM heatmaps WHERE match(current_url, ${heatmapUrlPatternToRegex(
                                  url
                              )}) AND timestamp >= now() - INTERVAL 30 DAY`
                            : hogql`SELECT count() FROM heatmaps WHERE trimRight(current_url, '/') = trimRight(${url}, '/') AND timestamp >= now() - INTERVAL 30 DAY`
                    let response: Awaited<ReturnType<typeof api.queryHogQL>> | null = null
                    try {
                        response = await api.queryHogQL(query, { scene: 'Heatmaps', productKey: 'heatmaps' })
                    } catch {
                        // A failed readiness check is educational and never blocks creation.
                    }
                    breakpoint()
                    if (url !== values.effectiveDataUrl) {
                        return { url, matchType, trigger, outcome: 'error', count: null }
                    }
                    if (!response) {
                        return { url, matchType, trigger, outcome: 'error', count: null }
                    }
                    const results = response.results as unknown[][] | undefined
                    const count = Number(results?.[0]?.[0] ?? 0)
                    return {
                        url,
                        matchType,
                        trigger,
                        outcome: count > 0 ? 'detected' : 'none',
                        count,
                    }
                },
            },
        ],
    })),

    reducers({
        currentStep: [
            'page' as HeatmapCreationStep,
            {
                applyStep: (_, { step }) => step,
                resetForPageChange: () => 'page',
            },
        ],
        furthestStep: [
            'page' as HeatmapCreationStep,
            {
                applyStep: (state, { step }) => (STEP_ORDER.indexOf(step) > STEP_ORDER.indexOf(state) ? step : state),
                resetForPageChange: () => 'page',
            },
        ],
        pageAccess: [
            null as HeatmapPageAccess | null,
            {
                setPageAccess: (_, { pageAccess }) => pageAccess,
                resetForPageChange: () => null,
            },
        ],
        recordingBackground: [
            null as RecordingBackgroundSelection | null,
            {
                selectRecordingBackground: (_, { storageKey, matchingRecordingCount }) => ({
                    storageKey,
                    matchingRecordingCount,
                }),
                resetForPageChange: () => null,
                setPageAccess: (state, { pageAccess }) => (pageAccess === 'login' ? state : null),
            },
        ],
        recordingHeatmapOpen: [
            false,
            {
                showRecordingHeatmap: () => true,
                closeRecordingHeatmap: () => false,
                resetForPageChange: () => false,
                setPageAccess: (state, { pageAccess }) => (pageAccess === 'login' ? state : false),
            },
        ],
        terminalOutcome: [
            null as 'created' | 'recording_handoff' | null,
            {
                creationCompleted: () => 'created',
                markRecordingHandoff: () => 'recording_handoff',
            },
        ],
    }),

    selectors({
        effectiveDataUrl: [
            (s) => [s.dataUrl, s.displayUrl],
            (dataUrl, displayUrl): string | null => dataUrl?.trim() || displayUrl?.trim() || null,
        ],
        pageStepBlockReason: [
            (s) => [s.displayUrl, s.isDisplayUrlValid, s.dataUrl, s.isBrowserUrlValid],
            (displayUrl, isDisplayUrlValid, dataUrl, isBrowserUrlValid): string | null =>
                getPageStepBlockReason({
                    displayUrl,
                    isDisplayUrlValid,
                    dataUrl,
                    isDataUrlValid: isBrowserUrlValid,
                }),
        ],
        isDisplayUrlAuthorized: [
            (s) => [s.displayUrl, s.checkUrlIsAuthorized],
            (displayUrl, checkUrlIsAuthorized): boolean => (displayUrl ? checkUrlIsAuthorized(displayUrl) : false),
        ],
        authorizationDisabledReason: [
            () => [],
            (): string | null => {
                if (inStorybook() || inStorybookTestRunner()) {
                    return null
                }
                return getAccessControlDisabledReason(
                    AccessControlResourceType.WebAnalytics,
                    AccessControlLevel.Editor,
                    undefined,
                    false
                )
            },
        ],
        backgroundStepBlockReason: [
            (s) => [s.pageAccess, s.type, s.isDisplayUrlAuthorized, s.recordingBackgroundData],
            (pageAccess, type, isDisplayUrlAuthorized, recordingBackgroundData): string | null =>
                getBackgroundStepBlockReason({
                    pageAccess,
                    type,
                    isDisplayUrlAuthorized,
                    hasRecordingBackground: !!recordingBackgroundData,
                }),
        ],
        reviewBlockReason: [
            (s) => [s.pageStepBlockReason, s.backgroundStepBlockReason],
            (pageStepBlockReason, backgroundStepBlockReason): string | null =>
                pageStepBlockReason ?? backgroundStepBlockReason,
        ],
        currentPageDataCheck: [
            (s) => [s.pageDataCheck, s.effectiveDataUrl],
            (pageDataCheck, effectiveDataUrl): HeatmapDataCheckResult | null =>
                pageDataCheck?.url === effectiveDataUrl ? pageDataCheck : null,
        ],
        recordingBackgroundData: [
            (s) => [s.recordingBackground],
            (recordingBackground): ReplayIframeData | null =>
                getStoredRecordingBackground(recordingBackground?.storageKey ?? null),
        ],
        analyticsBackgroundType: [
            (s) => [s.pageAccess, s.type],
            (pageAccess, type): HeatmapType | 'recording' => (pageAccess === 'login' ? 'recording' : type),
        ],
        hasMatchingData: [
            (s) => [s.currentPageDataCheck],
            (currentPageDataCheck): boolean | null =>
                currentPageDataCheck?.outcome === 'detected'
                    ? true
                    : currentPageDataCheck?.outcome === 'none'
                      ? false
                      : null,
        ],
        captureEnabled: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.heatmaps_opt_in],
        creationContext: [
            (s) => [s.captureEnabled, s.hasMatchingData, s.type],
            (captureEnabled, hasMatchingData, type): HeatmapCreationContext => ({
                creation_flow: 'wizard',
                capture_enabled: captureEnabled,
                has_matching_data: hasMatchingData,
                page_access: 'public',
                background_type: type,
            }),
        ],
    }),

    listeners(({ actions, values }) => {
        const onUrlChanged = (): void => {
            actions.resetForPageChange()
            actions.requestPageDataCheck('automatic')
        }
        return {
            navigateToStep: ({ step }) => {
                if (STEP_ORDER.indexOf(step) <= STEP_ORDER.indexOf(values.furthestStep)) {
                    actions.applyStep(step)
                }
            },
            continueFromPage: () => {
                if (values.pageStepBlockReason) {
                    return
                }
                captureWizardStepCompleted(values, 'page')
                actions.applyStep('background')
            },
            continueFromBackground: () => {
                if (values.backgroundStepBlockReason) {
                    return
                }
                captureWizardStepCompleted(values, 'background')
                actions.applyStep('review')
            },
            goBack: () => {
                const currentIndex = STEP_ORDER.indexOf(values.currentStep)
                if (currentIndex > 0) {
                    actions.applyStep(STEP_ORDER[currentIndex - 1])
                }
            },
            setPageAccess: ({ pageAccess }) => {
                if (pageAccess === 'login') {
                    actions.setType('screenshot')
                }
            },
            resetForPageChange: () => {
                actions.setType('screenshot')
            },
            setDisplayUrl: onUrlChanged,
            setDataUrl: onUrlChanged,
            requestPageDataCheck: ({ trigger }) => {
                if (values.pageStepBlockReason || !values.effectiveDataUrl) {
                    actions.checkPageData({ url: null, matchType: 'exact', trigger })
                    return
                }
                actions.checkPageData({
                    url: values.effectiveDataUrl,
                    matchType: isUrlPattern(values.effectiveDataUrl) ? 'pattern' : 'exact',
                    trigger,
                })
            },
            checkPageDataSuccess: ({ pageDataCheck }) => {
                if (!pageDataCheck || pageDataCheck.url !== values.effectiveDataUrl) {
                    return
                }
                posthog.capture('in-app heatmap creation data checked', {
                    trigger: pageDataCheck.trigger,
                    result: pageDataCheck.outcome,
                    match_type: pageDataCheck.matchType,
                })
            },
            authorizeDisplayUrl: () => {
                const origin = getAuthorizationOrigin(values.displayUrl)
                if (!origin || values.authorizationDisabledReason || values.isDisplayUrlAuthorized) {
                    return
                }
                actions.addUrl(origin)
            },
            markRecordingHandoff: ({ matchingRecordingCount }) => {
                posthog.capture('in-app heatmap creation recording handoff', {
                    matching_recording_count: matchingRecordingCount,
                })
            },
            completeHeatmapBackgroundSelection: ({ storageKey }) => {
                if (values.modalContext?.type !== 'heatmap-background-selection') {
                    return
                }
                actions.selectRecordingBackground(storageKey, values.modalContext.matchingRecordingCount)
                captureWizardStepCompleted(values, 'background', { page_access: 'login', background_type: 'recording' })
                actions.applyStep('review')
            },
            openRecordingHeatmap: () => {
                if (!values.recordingBackground || !values.recordingBackgroundData) {
                    return
                }
                const replayIframeData = {
                    ...values.recordingBackgroundData,
                    url: values.effectiveDataUrl ?? values.recordingBackgroundData.url,
                }
                localStorage.setItem(values.recordingBackground.storageKey, JSON.stringify(replayIframeData))
                actions.setReplayIframeData(replayIframeData)
                actions.showRecordingHeatmap()
            },
            finishRecordingHeatmap: () => {
                if (values.terminalOutcome || !values.recordingBackground || !values.recordingHeatmapOpen) {
                    return
                }
                captureWizardStepCompleted(values, 'review', { page_access: 'login', background_type: 'recording' })
                actions.markRecordingHandoff(values.recordingBackground.matchingRecordingCount)
                router.actions.push(urls.heatmaps())
            },
            creationCompleted: () => {
                captureWizardStepCompleted(values, 'review')
            },
        }
    }),

    afterMount(({ actions, values, cache }) => {
        cache.wizardStarted = true
        posthog.capture('in-app heatmap creation wizard started', {
            capture_enabled: values.captureEnabled,
        })
        if (!values.pageStepBlockReason && values.effectiveDataUrl) {
            actions.requestPageDataCheck('automatic')
        }
    }),

    beforeUnmount(({ values, cache }) => {
        if (cache.wizardStarted && !values.terminalOutcome) {
            posthog.capture('in-app heatmap creation wizard abandoned', {
                furthest_step: values.furthestStep,
                capture_enabled: values.captureEnabled,
                has_matching_data: values.hasMatchingData,
                page_access: values.pageAccess,
                background_type: values.analyticsBackgroundType,
            })
        }
    }),
])
