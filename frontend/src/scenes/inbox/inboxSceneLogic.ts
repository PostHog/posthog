import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { signalSourcesLogic } from './signalSourcesLogic'
import { SignalReport, SignalReportArtefact, SignalReportArtefactResponse } from './types'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect({
        values: [signalSourcesLogic, ['hasNoSources']],
    }),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
    }),

    loaders(({ values }) => ({
        reports: [
            [] as SignalReport[],
            {
                loadReports: async () => {
                    const response = await api.signalReports.list()
                    return response.results
                },
            },
        ],
        artefacts: [
            {} as Record<string, SignalReportArtefact[]>,
            {
                loadArtefacts: async ({ reportId }: { reportId: string }) => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(reportId)
                    return { ...values.artefacts, [reportId]: response.results }
                },
            },
        ],
    })),

    reducers({
        selectedReportId: [
            null as string | null,
            {
                setSelectedReportId: (_, { id }) => id,
            },
        ],
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        isRunningSessionAnalysis: [
            false,
            {
                runSessionAnalysis: () => true,
                runSessionAnalysisSuccess: () => false,
                runSessionAnalysisFailure: () => false,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'inbox',
                    name: sceneConfigurations[Scene.Inbox].name,
                    iconType: 'inbox',
                },
            ],
        ],
        filteredReports: [
            (s) => [s.reports, s.searchQuery],
            (reports: SignalReport[], searchQuery: string): SignalReport[] => {
                if (!searchQuery.trim()) {
                    return reports
                }
                const q = searchQuery.toLowerCase()
                return reports.filter((r) => r.title?.toLowerCase().includes(q) || r.summary?.toLowerCase().includes(q))
            },
        ],
        selectedReport: [
            (s) => [s.reports, s.selectedReportId],
            (reports: SignalReport[], selectedReportId: string | null): SignalReport | null =>
                reports.find((r) => r.id === selectedReportId) ?? null,
        ],
        shouldShowEnablingCtaOnMobile: [
            (s) => [s.hasNoSources, s.filteredReports, s.reportsLoading],
            (hasNoSources: boolean, filteredReports: SignalReport[], reportsLoading: boolean): boolean =>
                hasNoSources && !reportsLoading && filteredReports.length === 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        setSelectedReportId: ({ id }) => {
            if (id && !values.artefacts[id]) {
                actions.loadArtefacts({ reportId: id })
            }
        },
        runSessionAnalysis: async () => {
            try {
                await api.signalReports.analyzeSessions()
                lemonToast.success('Session analysis completed')
                actions.runSessionAnalysisSuccess()
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to run session analysis'
                lemonToast.error(errorMessage)
                actions.runSessionAnalysisFailure(errorMessage)
            }
        },
        runSessionAnalysisSuccess: () => {
            actions.loadReports()
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadReports()
        },
    })),

    actionToUrl(({ values }) => ({
        setSelectedReportId: () => [
            values.selectedReportId ? urls.inbox(values.selectedReportId) : urls.inbox(),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.inbox()]: () => {
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
        },
        [urls.inbox(':reportId')]: ({ reportId }: { reportId?: string }) => {
            const id = reportId ?? null
            if (values.selectedReportId !== id) {
                actions.setSelectedReportId(id)
            }
        },
    })),
])
