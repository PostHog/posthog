import { useActions, useValues } from 'kea'

import { storiesLogic } from './storiesLogic'
import type { storyGroup } from './storiesMap'
import { StoriesModal } from './StoriesModal'

export const PosthogStoriesContainer = (): JSX.Element => {
    const { stories } = useValues(storiesLogic)
    const { setActiveGroupIndex, setOpenStoriesModal, setActiveStoryIndex } = useActions(storiesLogic)

    return (
        <>
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
                            <div className="w-16 h-16 rounded-full overflow-hidden border-2 border-primary">
                                <img
                                    src={storyGroup.stories[0]?.thumbnailUrl}
                                    alt={storyGroup.title}
                                    className="w-full h-full object-cover"
                                />
                            </div>
                            <span className="text-xs truncate max-w-[64px]">{storyGroup.title}</span>
                        </div>
                    ))}
            </div>
            <StoriesModal />
        </>
    )
}
