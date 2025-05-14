import './StoriesModal.scss'

import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useCallback, useEffect, useMemo } from 'react'
import Stories from 'react-insta-stories'
import { Story } from 'react-insta-stories/dist/interfaces'

import { storiesLogic } from './storiesLogic'
import type { story } from './storiesMap'

export const StoriesModal = (): JSX.Element | null => {
    const {
        openStoriesModal,
        stories: storyGroups,
        activeGroupIndex,
        activeGroup,
        activeStoryIndex,
        activeStory,
        isStoryViewed,
    } = useValues(storiesLogic)
    const { setOpenStoriesModal, setActiveStoryIndex, setActiveGroupIndex, markStoryAsViewed, markGroupAsViewed } =
        useActions(storiesLogic)

    // Mark story as viewed when it becomes active
    useEffect(() => {
        if (activeStory && openStoriesModal) {
            markStoryAsViewed(activeStory.id)
        }
    }, [activeStory, markStoryAsViewed, openStoriesModal])

    // Mark group as viewed when all stories are viewed
    useEffect(() => {
        if (activeGroup && activeGroup.stories.every((story) => isStoryViewed(story.id))) {
            markGroupAsViewed(activeGroup.id)
        }
    }, [activeGroup, markGroupAsViewed, isStoryViewed])

    const maxStoryIndex = useMemo(() => {
        return activeGroup?.stories.length || 0
    }, [activeGroup])

    const isLastStoryGroup = useMemo(() => {
        return activeGroupIndex === storyGroups.length - 1
    }, [activeGroupIndex, storyGroups])

    const handleClose = useCallback(
        (forceClose: boolean) => {
            if (isLastStoryGroup || forceClose) {
                setOpenStoriesModal(false)
            } else {
                setActiveGroupIndex(activeGroupIndex + 1)
                setActiveStoryIndex(0)
            }
        },
        [setOpenStoriesModal, setActiveStoryIndex, setActiveGroupIndex, isLastStoryGroup, activeGroupIndex]
    )

    const handlePrevious = useCallback(() => {
        // if we are in the first story, go to the last story in the previous group
        if (activeStoryIndex === 0 && activeGroupIndex > 0) {
            setActiveGroupIndex(activeGroupIndex - 1)
            setActiveStoryIndex(storyGroups[activeGroupIndex - 1].stories.length - 1)
        } else {
            setActiveStoryIndex(activeStoryIndex - 1)
        }
    }, [activeStoryIndex, activeGroupIndex, storyGroups, setActiveStoryIndex, setActiveGroupIndex])

    const handleStoryStart = useCallback(
        (index: number) => {
            setActiveStoryIndex(index)
        },
        [setActiveStoryIndex]
    )

    if (!openStoriesModal || !activeGroup) {
        return null
    }

    const stories = activeGroup.stories.map(
        (story: story): Story => ({
            url: story.mediaUrl,
            type: story.type,
            header: {
                heading: story.title,
                subheading: story.description || '',
                profileImage: story.thumbnailUrl,
            },
            seeMore: () =>
                story.link
                    ? (() => {
                          setOpenStoriesModal(false)
                          window.open(story.link, '_self')
                      })()
                    : undefined,
            preloadResource: true,
        })
    )

    return (
        <LemonModal isOpen={openStoriesModal} onClose={() => handleClose(true)} simple className="StoriesModal__modal">
            <Stories
                stories={stories}
                defaultInterval={1500}
                width="100%"
                currentIndex={activeStoryIndex}
                onNext={() => setActiveStoryIndex(Math.min(activeStoryIndex + 1, maxStoryIndex))}
                onPrevious={handlePrevious}
                onAllStoriesEnd={() => handleClose(false)}
                onStoryEnd={() => {
                    setActiveStoryIndex(Math.min(activeStoryIndex + 1, maxStoryIndex))
                }}
                onStoryStart={handleStoryStart}
                storyContainerStyles={{
                    width: '100%',
                    height: '100%',
                    maxWidth: '400px',
                    minWidth: '400px',
                }}
            />
        </LemonModal>
    )
}
