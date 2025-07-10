import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronRight } from '@posthog/icons'

import { StoriesModal } from './StoriesModal'
import { storiesLogic } from './storiesLogic'

export const PosthogStoriesContainer = (): JSX.Element => {
    const { stories, isStoryViewed, storiesCollapsed } = useValues(storiesLogic)
    const { setActiveGroupIndex, setOpenStoriesModal, setActiveStoryIndex, toggleStoriesCollapsed } =
        useActions(storiesLogic)

    // Pre-compute viewed status for each story group to avoid redundant calculations
    const storiesWithViewedStatus = stories.map((storyGroup) => ({
        ...storyGroup,
        hasViewedEntireGroup: storyGroup.stories.every((story) => isStoryViewed(story.id)),
    }))

    // Sort stories so viewed groups appear at the end
    const sortedStories = [...storiesWithViewedStatus].sort((a, b) => {
        if (a.hasViewedEntireGroup && !b.hasViewedEntireGroup) {
            return 1
        } // a goes to end
        if (!a.hasViewedEntireGroup && b.hasViewedEntireGroup) {
            return -1
        } // b goes to end
        return 0 // maintain original order for same type
    })

    return (
        <>
            <div className="mb-2 flex items-center gap-2 px-1">
                <button
                    onClick={toggleStoriesCollapsed}
                    className="flex cursor-pointer items-center gap-2 transition-opacity hover:opacity-70"
                    title={storiesCollapsed ? 'Show stories' : 'Hide stories'}
                >
                    <IconChevronRight
                        className={`h-3 w-3 opacity-80 transition-transform ${storiesCollapsed ? '' : 'rotate-90'}`}
                    />
                    <span className="text-text-3000 text-sm font-medium">Stories</span>
                </button>
            </div>
            {!storiesCollapsed && (
                <div className="PosthogStoriesContainer flex flex-row gap-4 overflow-x-auto px-4">
                    {sortedStories.map((storyGroup) => {
                        const { hasViewedEntireGroup } = storyGroup
                        const nextStoryIndex = hasViewedEntireGroup
                            ? 0
                            : storyGroup.stories.findIndex((story) => !isStoryViewed(story.id))
                        const nextStory = storyGroup.stories[nextStoryIndex]

                        // Find original index for analytics
                        const originalIndex = stories.findIndex((s) => s.id === storyGroup.id)

                        return (
                            <div
                                key={storyGroup.id}
                                className={`flex cursor-pointer flex-col items-center gap-2 transition-opacity hover:opacity-80 ${
                                    hasViewedEntireGroup ? 'opacity-75' : ''
                                }`}
                                onClick={() => {
                                    posthog.capture('posthog_story_group_clicked', {
                                        story_group_id: storyGroup.id,
                                        group_title: storyGroup.title,
                                        group_thumbnail_url: nextStory.thumbnailUrl,
                                        group_index: originalIndex,
                                    })
                                    setActiveStoryIndex(nextStoryIndex)
                                    setActiveGroupIndex(originalIndex)
                                    setOpenStoriesModal(true)
                                }}
                            >
                                <div
                                    className={`w-15 h-15 relative rounded-full ${
                                        hasViewedEntireGroup ? 'bg-gray-300 p-[1px]' : 'bg-orange-500 p-[2px]'
                                    }`}
                                >
                                    <div className="bg-bg-light h-full w-full overflow-hidden rounded-full p-[2px]">
                                        <div className="relative h-full w-full overflow-hidden rounded-full">
                                            <img
                                                src={nextStory.thumbnailUrl}
                                                alt={storyGroup.title}
                                                className="h-full w-full object-cover"
                                            />
                                            {nextStory.type === 'video' && (
                                                <div className="video-icon absolute inset-0 flex items-center justify-center bg-black/20">
                                                    <svg
                                                        className="h-6 w-6 text-white"
                                                        fill="currentColor"
                                                        viewBox="0 0 24 24"
                                                    >
                                                        <path d="M8 5v14l11-7z" />
                                                    </svg>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <span className="line-clamp-2 max-w-[64px] text-center text-xs">
                                    {storyGroup.title}
                                </span>
                            </div>
                        )
                    })}
                </div>
            )}
            <StoriesModal />
        </>
    )
}
