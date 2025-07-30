import './stories.scss'

import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { storiesLogicType } from './storiesLogicType'
import type { storyGroup } from './storiesMap'
import { storiesMap } from './storiesMap'

const STORAGE_KEY = 'posthog_stories_viewed'
const COLLAPSED_STORAGE_KEY = 'posthog_stories_collapsed'

export interface ViewedStories {
    storyIds: string[]
}

export const storiesLogic = kea<storiesLogicType>([
    path(['layout', 'navigation', 'PosthogStories', 'storiesLogic']),
    actions({
        setActiveGroupIndex: (groupIndex: number) => ({ groupIndex }),
        setActiveStoryIndex: (storyIndex: number) => ({ storyIndex }),
        setOpenStoriesModal: (openStoriesModal: boolean) => ({ openStoriesModal }),
        markStoryAsViewed: (storyId: string) => ({ storyId }),
        toggleStoriesCollapsed: true,
        setInitialCollapsedState: (collapsed: boolean) => ({ collapsed }),
    }),

    loaders(() => ({
        viewedStories: [
            { storyIds: [] } as ViewedStories,
            {
                loadViewedStories: async () => {
                    try {
                        const stored = localStorage.getItem(STORAGE_KEY)
                        return stored ? JSON.parse(stored) : { storyIds: [] }
                    } catch {
                        return { storyIds: [] }
                    }
                },
            },
        ],
        collapsedState: [
            false as boolean,
            {
                loadCollapsedState: async () => {
                    try {
                        const stored = localStorage.getItem(COLLAPSED_STORAGE_KEY)
                        return stored !== null ? JSON.parse(stored) : false
                    } catch {
                        return false
                    }
                },
            },
        ],
    })),

    reducers({
        stories: [storiesMap],
        openStoriesModalValue: [
            false,
            {
                setOpenStoriesModal: (_, { openStoriesModal }) => openStoriesModal,
            },
        ],
        activeGroupIndexValue: [
            0,
            {
                setActiveGroupIndex: (_, { groupIndex }) => groupIndex,
            },
        ],
        activeStoryIndexValue: [
            0,
            {
                setActiveStoryIndex: (_, { storyIndex }) => storyIndex,
            },
        ],
        storiesCollapsedValue: [
            false,
            {
                toggleStoriesCollapsed: (state) => !state,
                setInitialCollapsedState: (_, { collapsed }) => collapsed,
                loadCollapsedStateSuccess: (_, { collapsedState }) => collapsedState,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        markStoryAsViewed: async ({ storyId }) => {
            const current = values.viewedStories
            if (!current.storyIds.includes(storyId)) {
                const updated = {
                    ...current,
                    storyIds: [...current.storyIds, storyId],
                }
                localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
                actions.loadViewedStories()
            }
        },
        toggleStoriesCollapsed: () => {
            // Save collapsed state to localStorage after toggling
            localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify(values.storiesCollapsed))
        },
        setInitialCollapsedState: ({ collapsed }) => {
            // Save collapsed state to localStorage when explicitly set
            localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify(collapsed))
        },
        loadCollapsedStateSuccess: () => {
            // If no stored collapsed state exists, set initial state based on unseen stories
            if (localStorage.getItem(COLLAPSED_STORAGE_KEY) === null) {
                actions.setInitialCollapsedState(!values.hasUnseenStories)
            }
        },
        loadViewedStoriesSuccess: () => {
            // Load collapsed state after viewed stories are loaded
            actions.loadCollapsedState()
        },
    })),

    selectors({
        activeGroup: [
            (s) => [s.stories, s.activeGroupIndex],
            (stories: storyGroup[], activeGroupIndex: number) => stories[activeGroupIndex] || null,
        ],
        activeStory: [
            (s) => [s.activeGroup, s.activeStoryIndex],
            (activeGroup: storyGroup | null, activeStoryIndex: number) =>
                activeGroup?.stories[activeStoryIndex] || null,
        ],
        openStoriesModal: [(s) => [s.openStoriesModalValue], (openStoriesModalValue: boolean) => openStoriesModalValue],
        activeGroupIndex: [(s) => [s.activeGroupIndexValue], (activeGroupIndexValue: number) => activeGroupIndexValue],
        activeStoryIndex: [(s) => [s.activeStoryIndexValue], (activeStoryIndexValue: number) => activeStoryIndexValue],
        storiesCollapsed: [(s) => [s.storiesCollapsedValue], (storiesCollapsedValue: boolean) => storiesCollapsedValue],
        hasUnseenStories: [
            (s) => [s.stories, s.viewedStories],
            (stories: storyGroup[], viewedStories: ViewedStories) =>
                stories.some((storyGroup) =>
                    storyGroup.stories.some((story) => !viewedStories.storyIds.includes(story.id))
                ),
        ],
        isStoryViewed: [
            (s) => [s.viewedStories],
            (viewedStories: ViewedStories) => (storyId: string) => viewedStories.storyIds.includes(storyId),
        ],
    }),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadViewedStories()
        },
    })),
])
