import { actions, kea, path, reducers, selectors } from 'kea'

import type { storiesLogicType } from './storiesLogicType'
import type { storyGroup } from './storiesMap'
import { storiesMap } from './storiesMap'

export const storiesLogic = kea<storiesLogicType>([
    path(['layout', 'navigation', 'PosthogStories', 'storiesLogic']),
    actions({
        setActiveGroupIndex: (groupIndex: number) => ({ groupIndex }),
        setActiveStoryIndex: (storyIndex: number) => ({ storyIndex }),
        setOpenStoriesModal: (openStoriesModal: boolean) => ({ openStoriesModal }),
    }),

    reducers({
        stories: [storiesMap, {}],
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
    }),

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
    }),
])
