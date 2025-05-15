import './StoriesModal.scss'

import { useActions, useValues } from 'kea'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import Stories from 'react-insta-stories'
import { Story } from 'react-insta-stories/dist/interfaces'

import { storiesLogic } from './storiesLogic'
import type { story } from './storiesMap'

interface StoryEndEventProps extends StoryEndEventPropsExtraProps {
    reason: string
    story_id: string
    story_title: string
    story_thumbnail_url: string
    time_spent_ms: number
    time_spent_seconds: number
    story_group_id: string
    story_group_title: string
}

interface StoryEndEventPropsExtraProps {
    next_story_id?: string
    next_story_title?: string
    next_story_thumbnail_url?: string
}

export const StoriesModal = (): JSX.Element | null => {
    const {
        openStoriesModal,
        stories: storyGroups,
        activeGroupIndex,
        activeGroup,
        activeStoryIndex,
        activeStory,
    } = useValues(storiesLogic)
    const { setOpenStoriesModal, setActiveStoryIndex, setActiveGroupIndex, markStoryAsViewed } =
        useActions(storiesLogic)
    const storyStartTimeRef = useRef<number>(Date.now())

    // Mark story as viewed when it becomes active
    useEffect(() => {
        if (activeStory && openStoriesModal) {
            markStoryAsViewed(activeStory.id)
        }
    }, [activeStory, markStoryAsViewed, openStoriesModal])

    const maxStoryIndex = useMemo(() => activeGroup?.stories.length || 0, [activeGroup])
    const isLastStoryGroup = useMemo(() => activeGroupIndex === storyGroups.length - 1, [activeGroupIndex, storyGroups])

    const handleClose = useCallback(
        (forceClose: boolean) => {
            const timeSpentMs = Date.now() - storyStartTimeRef.current
            posthog.capture('posthog_story_closed', {
                reason: forceClose ? 'force_close' : 'natural_close',
                story_id: activeGroup?.stories[activeStoryIndex].id,
                story_title: activeGroup?.stories[activeStoryIndex].title,
                story_thumbnail_url: activeGroup?.stories[activeStoryIndex].thumbnailUrl,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
                time_spent_ms: timeSpentMs,
                time_spent_seconds: Math.round(timeSpentMs / 1000),
            })

            if (isLastStoryGroup || forceClose) {
                setOpenStoriesModal(false)
            } else {
                setActiveGroupIndex(activeGroupIndex + 1)
                setActiveStoryIndex(0)
            }
        },
        [
            setOpenStoriesModal,
            setActiveStoryIndex,
            setActiveGroupIndex,
            isLastStoryGroup,
            activeGroupIndex,
            activeGroup,
            activeStoryIndex,
        ]
    )

    const handlePrevious = useCallback(() => {
        if (activeStoryIndex === 0 && activeGroupIndex > 0) {
            setActiveGroupIndex(activeGroupIndex - 1)
            setActiveStoryIndex(storyGroups[activeGroupIndex - 1].stories.length - 1)
            sendStoryEndEvent('previous')
        } else if (activeStoryIndex > 0) {
            setActiveStoryIndex(activeStoryIndex - 1)
            sendStoryEndEvent('previous')
        } else {
            setActiveStoryIndex(0)
        }
    }, [activeGroup, activeStoryIndex, activeGroupIndex, storyGroups, setActiveStoryIndex, setActiveGroupIndex])

    const handleStoryStart = useCallback(
        (index: number) => {
            storyStartTimeRef.current = Date.now()
            posthog.capture('posthog_story_started', {
                event: 'started',
                story_id: activeGroup?.stories[index].id,
                story_title: activeGroup?.stories[index].title,
                story_thumbnail_url: activeGroup?.stories[index].thumbnailUrl,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
            })
            setActiveStoryIndex(index)
        },
        [setActiveStoryIndex, activeGroup]
    )

    const sendStoryEndEvent = useCallback(
        (reason: string, extraProps?: StoryEndEventPropsExtraProps) => {
            const timeSpentMs = Date.now() - storyStartTimeRef.current
            const props: StoryEndEventProps = {
                reason: reason,
                story_id: activeGroup?.stories[activeStoryIndex].id,
                story_title: activeGroup?.stories[activeStoryIndex].title,
                story_thumbnail_url: activeGroup?.stories[activeStoryIndex].thumbnailUrl,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
                time_spent_ms: timeSpentMs,
                time_spent_seconds: Math.round(timeSpentMs / 1000),
                ...(extraProps || {}),
            }
            posthog.capture('posthog_story_ended', props)
        },
        [activeGroup, activeStoryIndex]
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
            seeMore: story.link
                ? () => {
                      sendStoryEndEvent('see_more')
                      setOpenStoriesModal(false)
                      window.open(story.link, '_self')
                      return null
                  }
                : undefined,
            preloadResource: true,
        })
    )

    return (
        <LemonModal isOpen={openStoriesModal} onClose={() => handleClose(true)} simple className="StoriesModal__modal">
            <Stories
                stories={stories}
                defaultInterval={3000}
                width="100%"
                height="100%"
                currentIndex={activeStoryIndex}
                onNext={() => {
                    if (!activeGroup?.stories[activeStoryIndex]) {
                        return
                    }
                    sendStoryEndEvent('next')
                    setActiveStoryIndex(Math.min(activeStoryIndex + 1, maxStoryIndex))
                }}
                onPrevious={handlePrevious}
                onAllStoriesEnd={() => handleClose(false)}
                onStoryEnd={() => {
                    sendStoryEndEvent('ended_naturally')
                    setActiveStoryIndex(Math.min(activeStoryIndex + 1, maxStoryIndex))
                }}
                onStoryStart={handleStoryStart}
                storyContainerStyles={{
                    maxWidth: '390px',
                    minWidth: '390px',
                    maxHeight: '700px',
                    minHeight: '700px',
                }}
            />
        </LemonModal>
    )
}
