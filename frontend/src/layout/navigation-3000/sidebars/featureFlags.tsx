import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { dayjs } from 'lib/dayjs'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { InsightVizNode, NodeKind } from '~/queries/schema'
import { BaseMathType, FeatureFlagType } from '~/types'

import { navigation3000Logic } from '../navigationLogic'
import { ExtendedListItem, SidebarCategory } from '../types'
import type { featureFlagsSidebarLogicType } from './featureFlagsType'
import { FuseSearchMatch } from './utils'

const fuse = new Fuse<FeatureFlagType>([], {
    // Note: For feature flags `name` is the description field
    keys: [{ name: 'key', weight: 2 }, 'name', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const featureFlagsSidebarLogic = kea<featureFlagsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'featureFlagsSidebarLogic']),
    connect({
        values: [
            featureFlagsLogic,
            ['featureFlags', 'featureFlagsLoading'],
            teamLogic,
            ['currentTeamId'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [featureFlagsLogic, ['updateFeatureFlag', 'loadFeatureFlags']],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [s.relevantFeatureFlags, s.featureFlagsLoading, s.currentTeamId, s.aggregationLabel],
            (relevantFeatureFlags, featureFlagsLoading, currentTeamId, aggregationLabel) => [
                {
                    key: 'feature-flags',
                    noun: 'feature flag',
                    loading: featureFlagsLoading,
                    onAdd: urls.featureFlag('new'),
                    items: relevantFeatureFlags.map(([featureFlag, matches]) => {
                        if (!featureFlag.id) {
                            throw new Error('Feature flag ID should never be missing in the sidebar')
                        }

                        const query: InsightVizNode = {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                series: [
                                    {
                                        event: '$pageview',
                                        name: '$pageview',
                                        kind: NodeKind.EventsNode,
                                        math: BaseMathType.UniqueUsers,
                                    },
                                ],
                                breakdownFilter: {
                                    breakdown: `$feature/${featureFlag.key}`,
                                    breakdown_type: 'event',
                                },
                            },
                        }

                        return {
                            key: featureFlag.id,
                            name: featureFlag.key,
                            url: urls.featureFlag(featureFlag.id),
                            summary: featureFlag.active ? (
                                groupFilters(featureFlag.filters, true, aggregationLabel)
                            ) : (
                                <i>Disabled</i>
                            ),
                            extraContextTop: dayjs(featureFlag.created_at),
                            extraContextBottom: `by ${featureFlag.created_by?.first_name || 'unknown'}`,
                            marker: { type: 'ribbon', status: featureFlag.active ? 'success' : 'danger' },
                            searchMatch: matches
                                ? {
                                      matchingFields: matches.map((match) =>
                                          match.key === 'name' ? 'description' : match.key
                                      ),
                                      nameHighlightRanges: matches.find((match) => match.key === 'key')?.indices,
                                  }
                                : null,
                            menuItems: [
                                {
                                    items: [
                                        {
                                            label: 'Edit',
                                            to: urls.featureFlag(featureFlag.id),
                                            onClick: () => {
                                                featureFlagLogic({ id: featureFlag.id as number }).mount()
                                                featureFlagLogic({
                                                    id: featureFlag.id as number,
                                                }).actions.editFeatureFlag(true)
                                            },
                                            disabledReason: !featureFlag.can_edit
                                                ? "You don't have permission to edit this feature flag."
                                                : null,
                                        },
                                    ],
                                },
                                {
                                    items: [
                                        {
                                            label: `${featureFlag.active ? 'Disable' : 'Enable'} flag`,
                                            onClick: () =>
                                                actions.updateFeatureFlag({
                                                    id: featureFlag.id as number,
                                                    payload: { active: !featureFlag.active },
                                                }),
                                            disabledReason: !featureFlag.can_edit
                                                ? "You don't have permission to edit this feature flag."
                                                : null,
                                        },
                                        {
                                            label: 'Copy flag key',
                                            onClick: () => {
                                                void copyToClipboard(featureFlag.key, 'feature flag key')
                                            },
                                        },
                                        {
                                            label: 'Try out in Insights',
                                            to: urls.insightNew(undefined, undefined, query),
                                            'data-attr': 'usage',
                                        },
                                    ],
                                },
                                {
                                    items: [
                                        {
                                            label: 'Delete feature flag',
                                            onClick: () => {
                                                void deleteWithUndo({
                                                    endpoint: `projects/${currentTeamId}/feature_flags`,
                                                    object: { name: featureFlag.key, id: featureFlag.id },
                                                    callback: actions.loadFeatureFlags,
                                                })
                                            },
                                            disabledReason: !featureFlag.can_edit
                                                ? "You don't have permission to edit this feature flag."
                                                : null,
                                            status: 'danger',
                                        },
                                    ],
                                },
                            ],
                        } as ExtendedListItem
                    }),
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, number] | null => {
                return activeScene === Scene.FeatureFlag && sceneParams.params.id
                    ? ['feature-flags', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        relevantFeatureFlags: [
            (s) => [s.featureFlags, navigation3000Logic.selectors.searchTerm],
            (featureFlags, searchTerm): [FeatureFlagType, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return featureFlags.map((featureFlag) => [featureFlag, null])
            },
        ],
    })),
    subscriptions({
        featureFlags: (featureFlags) => {
            fuse.setCollection(featureFlags)
        },
    }),
])
