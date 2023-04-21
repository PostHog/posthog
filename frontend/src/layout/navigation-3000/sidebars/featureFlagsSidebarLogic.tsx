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
            sceneLogic,
            ['activeScene', 'sceneParams'],
        ],
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
    selectors({
        isLoading: [(s) => [s.featureFlagsLoading], (featureFlagsLoading) => featureFlagsLoading],
        contents: [
            (s) => [s.relevantFeatureFlags],
            (relevantFeatureFlags) =>
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
    }),
    subscriptions({
        featureFlags: (featureFlags) => {
            fuse.setCollection(featureFlags)
        },
    }),
])
