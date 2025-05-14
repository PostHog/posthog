import { useActions, useValues } from 'kea'

import { storiesLogic } from './storiesLogic'
import type { storyGroup } from './storiesMap'
import { StoriesModal } from './StoriesModal'

export const PosthogStoriesContainer = (): JSX.Element => {
    const { stories } = useValues(storiesLogic)
    const { setActiveGroupIndex, setOpenStoriesModal, setActiveStoryIndex } = useActions(storiesLogic)

    return (
        <>
            <div className="text-sm text-text-3000">Check our features in action!</div>
            <div className="PosthogStoriesContainer flex flex-row gap-4 p-4 overflow-x-auto">
                {stories
                    .sort((a: storyGroup, b: storyGroup) => a.order - b.order)
                    .map((storyGroup: storyGroup, index: number) => (
                        <div
                            key={storyGroup.id}
                            className="flex flex-col items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
                            onClick={() => {
                                setActiveStoryIndex(0)
                                setActiveGroupIndex(index)
                                setOpenStoriesModal(true)
                            }}
                        >
                            <div className="w-16 h-16 rounded-full overflow-hidden border-2 border-primary relative">
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
                            </div>
                            <span className="text-xs line-clamp-2 text-center max-w-[77px]">{storyGroup.title}</span>
                        </div>
                    ))}
            </div>
            <StoriesModal />
        </>
    )
}
