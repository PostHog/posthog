import { IconPlaylist } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { storiesLogic } from './storiesLogic'
import type { storyGroup } from './storiesMap'
import { StoriesModal } from './StoriesModal'

export const PosthogStoriesContainer = (): JSX.Element => {
    const { stories, isStoryViewed, storiesCollapsed } = useValues(storiesLogic)
    const { setActiveGroupIndex, setOpenStoriesModal, setActiveStoryIndex, toggleStoriesCollapsed } =
        useActions(storiesLogic)

    return (
        <>
            <div className="flex items-center gap-2 mb-2 px-1">
                <button
                    onClick={toggleStoriesCollapsed}
                    className="flex items-center gap-2 hover:opacity-70 transition-opacity cursor-pointer"
                    title={storiesCollapsed ? 'Show stories' : 'Hide stories'}
                >
                    <IconPlaylist className="text-lg opacity-80" />
                    <span className="text-sm font-medium text-text-3000">Video updates</span>
                </button>
            </div>
            {!storiesCollapsed && (
                <div className="PosthogStoriesContainer flex flex-row gap-4 px-4 overflow-x-auto">
                    {stories.map((storyGroup: storyGroup, index: number) => {
                        const hasViewedEntireGroup = storyGroup.stories.every((story) => isStoryViewed(story.id))
                        const nextStoryIndex = hasViewedEntireGroup
                            ? 0
                            : storyGroup.stories.findIndex((story) => !isStoryViewed(story.id))
                        const nextStory = storyGroup.stories[nextStoryIndex]

                        return (
                            <div
                                key={storyGroup.id}
                                className={`flex flex-col items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity ${
                                    hasViewedEntireGroup ? 'opacity-60' : ''
                                }`}
                                onClick={() => {
                                    posthog.capture('posthog_story_group_clicked', {
                                        story_group_id: storyGroup.id,
                                        group_title: storyGroup.title,
                                        group_thumbnail_url: nextStory.thumbnailUrl,
                                    })
                                    setActiveStoryIndex(nextStoryIndex)
                                    setActiveGroupIndex(index)
                                    setOpenStoriesModal(true)
                                }}
                            >
                                <div className="w-15 h-15 rounded-full p-[2px] bg-orange-500 relative">
                                    <div className="w-full h-full rounded-full overflow-hidden bg-bg-light p-[2px]">
                                        <div className="w-full h-full rounded-full overflow-hidden relative">
                                            <img
                                                src={nextStory.thumbnailUrl}
                                                alt={storyGroup.title}
                                                className="w-full h-full object-cover"
                                            />
                                            {nextStory.type === 'video' && (
                                                <div className="absolute inset-0 flex items-center justify-center bg-black/20 video-icon">
                                                    <svg
                                                        className="w-6 h-6 text-white"
                                                        fill="currentColor"
                                                        viewBox="0 0 24 24"
                                                        xmlns="http://www.w3.org/2000/svg"
                                                    >
                                                        <path d="M8 5v14l11-7z" />
                                                    </svg>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                                <span className="text-xs line-clamp-2 text-center max-w-[64px]">
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
