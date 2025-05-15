import { useActions, useValues } from 'kea'

import { storiesLogic } from './storiesLogic'
import type { storyGroup } from './storiesMap'
import { StoriesModal } from './StoriesModal'

export const PosthogStoriesContainer = (): JSX.Element => {
    const { stories, isStoryViewed } = useValues(storiesLogic)
    const { setActiveGroupIndex, setOpenStoriesModal, setActiveStoryIndex } = useActions(storiesLogic)

    return (
        <>
            <div
                className="text-sm text-text-3000"
                onClick={() => {
                    // reset local storage for testing purposes TODO REMOVE LATER
                    localStorage.removeItem('posthog_stories_viewed')
                }}
            >
                Check our features in action!
            </div>
            <div className="PosthogStoriesContainer flex flex-row gap-4 p-4 overflow-x-auto">
                {stories
                    .sort((a: storyGroup, b: storyGroup) => a.order - b.order)
                    .map((storyGroup: storyGroup, index: number) => {
                        const isViewed = storyGroup.stories.every((story) => isStoryViewed(story.id))
                        const firstStoryViewed = storyGroup.stories[0] ? isStoryViewed(storyGroup.stories[0].id) : false
                        return (
                            <div
                                key={storyGroup.id}
                                className={`flex flex-col items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity ${
                                    isViewed ? 'opacity-60' : ''
                                }`}
                                onClick={() => {
                                    const firstNotViewedIndex = storyGroup.stories.findIndex(
                                        (story) => !isStoryViewed(story.id)
                                    )
                                    setActiveStoryIndex(firstNotViewedIndex >= 0 ? firstNotViewedIndex : 0)
                                    setActiveGroupIndex(index)
                                    setOpenStoriesModal(true)
                                }}
                            >
                                <div
                                    className={`w-16 h-16 rounded-full overflow-hidden relative ${
                                        isViewed
                                            ? 'border-2 border-primary'
                                            : 'p-[3px] bg-gradient-to-tr from-[#f09433] via-[#e6683c] via-[#dc2743] via-[#cc2366] to-[#bc1888]'
                                    }`}
                                >
                                    <div className="w-full h-full rounded-full overflow-hidden bg-white">
                                        <img
                                            src={storyGroup.stories[0]?.thumbnailUrl}
                                            alt={storyGroup.title}
                                            className="w-full h-full object-cover"
                                        />
                                        {storyGroup.stories[0]?.type === 'video' && (
                                            <div className="absolute inset-0 flex items-center justify-center bg-black/20">
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
                                        {firstStoryViewed && (
                                            <div className="absolute bottom-0 right-0 bg-primary text-white rounded-full w-5 h-5 flex items-center justify-center text-xs">
                                                ✓
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <span className="text-xs line-clamp-2 text-center max-w-[77px]">
                                    {storyGroup.title}
                                </span>
                            </div>
                        )
                    })}
            </div>
            <StoriesModal />
        </>
    )
}
