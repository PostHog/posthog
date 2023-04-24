import { dayjs } from 'lib/dayjs'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'
import { featureFlagsLogic } from 'scenes/feature-flags/featureFlagsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { ExtendedListItem } from '../types'
import type { featureFlagsSidebarLogicType } from './featureFlagsSidebarLogicType'
import Fuse from 'fuse.js'
import { FeatureFlagType } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { copyToClipboard, deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

const fuse = new Fuse<FeatureFlagType>([], {
    keys: ['key', 'name', 'tags'],
    threshold: 0.3,
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
        ],
        actions: [featureFlagsLogic, ['updateFeatureFlag', 'loadFeatureFlags']],
    }),
    actions({
        setIsSearchShown: (isSearchShown: boolean) => ({ isSearchShown }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        isSearchShown: [
            false,
            {
                setIsSearchShown: (_, { isSearchShown }) => isSearchShown,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
    }),
    selectors(({ actions }) => ({
        isLoading: [(s) => [s.featureFlagsLoading], (featureFlagsLoading) => featureFlagsLoading],
        contents: [
            (s) => [s.relevantFeatureFlags, s.currentTeamId],
            (relevantFeatureFlags, currentTeamId) =>
                relevantFeatureFlags.map((featureFlag) => {
                    if (!featureFlag.id) {
                        throw new Error('Feature flag ID should never be missing in the sidebar')
                    }
                    return {
                        key: featureFlag.id,
                        name: featureFlag.key,
                        url: urls.featureFlag(featureFlag.id),
                        summary: featureFlag.active ? groupFilters(featureFlag.filters.groups, true) : <i>Disabled</i>,
                        extraContextTop: dayjs(featureFlag.created_at),
                        extraContextBottom: `by ${featureFlag.created_by?.first_name || 'unknown'}`,
                        marker: { type: 'ribbon', status: featureFlag.active ? 'success' : 'danger' },
                        menuItems: [
                            {
                                items: [
                                    {
                                        label: 'Copy feature flag key',
                                        onClick: () => {
                                            copyToClipboard(featureFlag.key, 'feature flag key')
                                        },
                                    },
                                    {
                                        label: `${featureFlag.active ? 'Disable' : 'Enable'} feature flag`,
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
                                        label: 'Edit',
                                        to: urls.featureFlag(featureFlag.id as number),
                                        onClick: () => {
                                            featureFlagLogic({ id: featureFlag.id as number }).mount()
                                            featureFlagLogic({ id: featureFlag.id as number }).actions.editFeatureFlag(
                                                true
                                            )
                                        },
                                        disabledReason: !featureFlag.can_edit
                                            ? "You don't have permission to edit this feature flag."
                                            : null,
                                    },
                                    {
                                        label: 'Try out in Insights',
                                        to: urls.insightNew({
                                            events: [
                                                { id: '$pageview', name: '$pageview', type: 'events', math: 'dau' },
                                            ],
                                            breakdown_type: 'event',
                                            breakdown: `$feature/${featureFlag.key}`,
                                        }),
                                        'data-attr': 'usage',
                                    },
                                ],
                            },
                            {
                                items: [
                                    {
                                        label: 'Delete feature flag',
                                        onClick: () => {
                                            deleteWithUndo({
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
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.FeatureFlag && sceneParams.params.id
                    ? parseInt(sceneParams.params.id)
                    : null
            },
        ],
        relevantFeatureFlags: [
            (s) => [s.featureFlags, s.searchTerm],
            (featureFlags, searchTerm) => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => result.item)
                }
                return featureFlags
            },
        ],
    })),
    subscriptions({
        featureFlags: (featureFlags) => {
            fuse.setCollection(featureFlags)
        },
    }),
])
