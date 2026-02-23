import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { sidePanelHealthLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import type { DataHealthIssue } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { Breadcrumb } from '~/types'

import type { pipelineStatusSceneLogicType } from './pipelineStatusSceneLogicType'

export type IssueTypeFilter = 'all' | DataHealthIssue['type']

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000

export const pipelineStatusSceneLogic = kea<pipelineStatusSceneLogicType>([
    path(['scenes', 'health', 'pipelineStatus', 'pipelineStatusSceneLogic']),
    tabAwareScene(),
    connect({
        values: [sidePanelHealthLogic, ['issues'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setTypeFilter: (filter: IssueTypeFilter) => ({ filter }),
        setSearchTerm: (term: string) => ({ term }),
        dismissIssue: (issueId: string) => ({ issueId }),
        undismissIssue: (issueId: string) => ({ issueId }),
        setShowDismissed: (show: boolean) => ({ show }),
    }),
    reducers({
        typeFilter: [
            'all' as IssueTypeFilter,
            {
                setTypeFilter: (_, { filter }) => filter,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        dismissedIssues: [
            {} as Record<string, number>,
            { persist: true },
            {
                dismissIssue: (state, { issueId }) => ({
                    ...state,
                    [issueId]: Date.now(),
                }),
                undismissIssue: (state, { issueId }) => {
                    const { [issueId]: _, ...rest } = state
                    return rest
                },
            },
        ],
        showDismissed: [
            false,
            {
                setShowDismissed: (_, { show }) => show,
            },
        ],
    }),
    selectors({
        activeDismissedIds: [
            (s) => [s.dismissedIssues],
            (dismissed: Record<string, number>): Set<string> => {
                const cutoff = Date.now() - THIRTY_DAYS_MS
                return new Set(
                    Object.entries(dismissed)
                        .filter(([, timestamp]) => timestamp > cutoff)
                        .map(([id]) => id)
                )
            },
        ],

        typeSummary: [
            (s) => [s.issues],
            (issues: DataHealthIssue[]): Record<DataHealthIssue['type'], number> => {
                const counts = {
                    materialized_view: 0,
                    external_data_sync: 0,
                    source: 0,
                    destination: 0,
                    transformation: 0,
                }
                for (const issue of issues) {
                    counts[issue.type] = (counts[issue.type] ?? 0) + 1
                }
                return counts
            },
        ],

        filteredIssues: [
            (s) => [s.issues, s.typeFilter, s.searchTerm, s.activeDismissedIds, s.showDismissed],
            (
                issues: DataHealthIssue[],
                typeFilter: IssueTypeFilter,
                searchTerm: string,
                dismissedIds: Set<string>,
                showDismissed: boolean
            ): DataHealthIssue[] => {
                let result = issues

                if (typeFilter !== 'all') {
                    result = result.filter((i) => i.type === typeFilter)
                }

                if (searchTerm.trim()) {
                    const lower = searchTerm.toLowerCase()
                    result = result.filter(
                        (i) =>
                            i.name.toLowerCase().includes(lower) || (i.error && i.error.toLowerCase().includes(lower))
                    )
                }

                if (!showDismissed) {
                    result = result.filter((i) => !dismissedIds.has(i.id))
                }

                return result
            },
        ],

        filteredIssueCount: [(s) => [s.filteredIssues], (issues: DataHealthIssue[]): number => issues.length],

        dismissedCount: [
            (s) => [s.issues, s.activeDismissedIds],
            (issues: DataHealthIssue[], dismissedIds: Set<string>): number => {
                return issues.filter((i) => dismissedIds.has(i.id)).length
            },
        ],

        isIssueDismissed: [
            (s) => [s.activeDismissedIds],
            (dismissedIds: Set<string>) =>
                (issueId: string): boolean =>
                    dismissedIds.has(issueId),
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Health,
                    name: sceneConfigurations[Scene.Health].name,
                    path: urls.health(),
                },
                {
                    key: Scene.PipelineStatus,
                    name: sceneConfigurations[Scene.PipelineStatus].name,
                },
            ],
        ],
    }),
    afterMount(({ values }) => {
        if (!values.featureFlags[FEATURE_FLAGS.PIPELINE_STATUS_PAGE]) {
            router.actions.replace(urls.health())
        }
    }),
])
