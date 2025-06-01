import './StoriesModal.scss'

import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import Stories from 'react-insta-stories'
import { Story } from 'react-insta-stories/dist/interfaces'

import { storiesLogic } from './storiesLogic'
import type { story } from './storiesMap'

const IMAGE_STORY_INTERVAL = 3500
const CRAZY_VIDEO_DURATION = 1000000 // this is a hack to make the video play for as long as a video would pla
const MIN_WIDTH = 320 // Minimum width in pixels
const MAX_WIDTH = 854 // Maximum width in pixels
const ASPECT_RATIO = 16 / 9 // 16:9 aspect ratio
const DEFAULT_WIDTH = 988

interface StoryEndEventProps extends StoryEndEventPropsExtraProps {
    reason: string
    story_id: string
    story_title: string
    story_thumbnail_url: string
    time_spent_ms: number
    time_spent_seconds: number
    story_group_id: string
    story_group_title: string
    story_watched_percentage?: number
}

interface StoryEndEventPropsExtraProps {
    next_story_id?: string
    next_story_title?: string
    next_story_thumbnail_url?: string
}

export const StoriesModal = (): JSX.Element | null => {
    const { windowSize } = useWindowSize()
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

    // Calculate dimensions based on window size and aspect ratio
    const dimensions = useMemo(() => {
        if (!windowSize.width || !windowSize.height) {
            return { width: DEFAULT_WIDTH, height: DEFAULT_WIDTH / ASPECT_RATIO }
        } // Default fallback

        // Calculate max available dimensions (90% of window)
        const maxAvailableWidth = Math.min(windowSize.width * 0.9, MAX_WIDTH)
        const maxAvailableHeight = Math.min(windowSize.height * 0.9, MAX_WIDTH / ASPECT_RATIO)

        // Calculate dimensions that fit both width and height constraints while maintaining aspect ratio
        let width = maxAvailableWidth
        let height = width / ASPECT_RATIO

        // If height is too large, scale down based on height
        if (height > maxAvailableHeight) {
            height = maxAvailableHeight
            width = height * ASPECT_RATIO
        }

        // Ensure minimum width
        if (width < MIN_WIDTH) {
            width = MIN_WIDTH
            height = width / ASPECT_RATIO
        }

        // Round to whole pixels
        width = Math.round(width)
        height = Math.round(height)

        return { width, height }
    }, [windowSize.width, windowSize.height])

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
                story_watched_percentage:
                    activeStory?.durationMs && activeStory?.durationMs > 0
                        ? Math.round((timeSpentMs / activeStory.durationMs) * 100)
                        : undefined,
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
            duration: story.durationMs,
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
                defaultInterval={activeStory?.type === 'video' ? CRAZY_VIDEO_DURATION : IMAGE_STORY_INTERVAL}
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
                    maxWidth: `${dimensions.width}px`,
                    minWidth: `${dimensions.width}px`,
                    maxHeight: `${dimensions.height}px`,
                    minHeight: `${dimensions.height}px`,
                }}
            />
        </LemonModal>
    )
}
