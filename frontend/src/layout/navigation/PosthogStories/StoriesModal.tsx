import './StoriesModal.scss'

import { IconChevronLeft, IconChevronRight, IconPauseFilled, IconPlayFilled, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Stories from 'react-insta-stories'
import { Story } from 'react-insta-stories/dist/interfaces'

import { storiesLogic } from './storiesLogic'
import type { story } from './storiesMap'

const IMAGE_STORY_INTERVAL = 3500
const CRAZY_VIDEO_DURATION = 1000000 // this is a hack to make the video play for as long as a video would play
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
    const [isPaused, setIsPaused] = useState(false)

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
        if (activeStoryIndex > 0) {
            setActiveStoryIndex(activeStoryIndex - 1)
        }
    }, [activeStoryIndex, setActiveStoryIndex])

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
        [activeGroup, activeStoryIndex, activeStory]
    )

    const handleNext = useCallback(() => {
        if (activeStoryIndex < maxStoryIndex - 1) {
            sendStoryEndEvent('next')
            setActiveStoryIndex(activeStoryIndex + 1)
        } else if (!isLastStoryGroup) {
            sendStoryEndEvent('next')
            setActiveGroupIndex(activeGroupIndex + 1)
            setActiveStoryIndex(0)
        }
    }, [
        activeStoryIndex,
        maxStoryIndex,
        isLastStoryGroup,
        activeGroupIndex,
        sendStoryEndEvent,
        setActiveStoryIndex,
        setActiveGroupIndex,
    ])

    const canGoPrevious = activeStoryIndex > 0
    const canGoNext = activeStoryIndex < maxStoryIndex - 1

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
                : () => <></>, // this is hack to hide the swipe component and not hide the profile component on stories
            preloadResource: true,
        })
    )

    return (
        <LemonModal
            isOpen={openStoriesModal}
            simple
            className="StoriesModal__modal"
            hideCloseButton={true}
            onClose={() => handleClose(true)}
        >
            <div className="flex flex-col">
                {/* Header with play/pause and close buttons */}
                <div className="flex justify-end gap-2">
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            e.preventDefault()
                            setIsPaused(!isPaused)
                        }}
                        className="text-white hover:text-gray-200 w-8 h-8 flex items-center justify-center transition-all duration-200 cursor-pointer"
                        title={isPaused ? 'Resume story' : 'Pause story'}
                    >
                        {isPaused ? <IconPlayFilled className="w-5 h-5" /> : <IconPauseFilled className="w-5 h-5" />}
                    </button>
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            e.preventDefault()
                            handleClose(true)
                        }}
                        className="text-white hover:text-gray-200 w-8 h-8 flex items-center justify-center transition-all duration-200 cursor-pointer"
                        title="Close stories"
                    >
                        <IconX className="w-5 h-5 [&>*]:fill-white" />
                    </button>
                </div>

                <div className="relative cursor-pointer flex-1 stories-container">
                    <Stories
                        stories={stories}
                        defaultInterval={activeStory?.type === 'video' ? CRAZY_VIDEO_DURATION : IMAGE_STORY_INTERVAL}
                        width="100%"
                        height="100%"
                        currentIndex={activeStoryIndex}
                        isPaused={isPaused}
                        onNext={() => {
                            if (!activeGroup?.stories[activeStoryIndex]) {
                                return
                            }
                            sendStoryEndEvent('next')

                            // Check if this is the last story in the current group
                            if (activeStoryIndex >= maxStoryIndex - 1) {
                                // Last story in group - close the modal
                                setOpenStoriesModal(false)
                            } else {
                                // Not last story - advance to next story in group
                                setActiveStoryIndex(activeStoryIndex + 1)
                            }
                        }}
                        onPrevious={handlePrevious}
                        onAllStoriesEnd={() => handleClose(false)}
                        onStoryEnd={() => {
                            sendStoryEndEvent('ended_naturally')

                            // Check if this is the last story in the current group
                            if (activeStoryIndex >= maxStoryIndex - 1) {
                                // Last story in group - close the modal
                                setOpenStoriesModal(false)
                            } else {
                                // Not last story - advance to next story in group
                                setActiveStoryIndex(activeStoryIndex + 1)
                            }
                        }}
                        onStoryStart={handleStoryStart}
                        storyContainerStyles={{
                            maxWidth: `${dimensions.width}px`,
                            minWidth: `${dimensions.width}px`,
                            maxHeight: `${dimensions.height}px`,
                            minHeight: `${dimensions.height}px`,
                            borderRadius: '4px',
                            overflow: 'hidden',
                        }}
                    />

                    {/* Navigation arrows */}
                    {canGoPrevious && (
                        <button
                            onClick={handlePrevious}
                            className="absolute left-4 top-1/2 transform -translate-y-1/2 bg-black/30 hover:bg-black/50 text-white rounded-full w-6 h-6 flex items-center justify-center transition-all duration-200 z-10"
                            title="Previous story"
                        >
                            <IconChevronLeft className="w-4 h-4" />
                        </button>
                    )}

                    {canGoNext && (
                        <button
                            onClick={handleNext}
                            className="absolute right-4 top-1/2 transform -translate-y-1/2 bg-black/30 hover:bg-black/50 text-white rounded-full w-6 h-6 flex items-center justify-center transition-all duration-200 z-10"
                            title="Next story"
                        >
                            <IconChevronRight className="w-4 h-4" />
                        </button>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
