import './StoriesModal.scss'

import { IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { storiesLogic } from './storiesLogic'
import { CloseOverlayAction, StoryType } from './storiesMap'
import type { story } from './storiesMap'
import { StoriesPlayer, Story } from './StoriesPlayer'

const IMAGE_STORY_INTERVAL = 6000
const MIN_WIDTH = 320 // Minimum width in pixels
const MAX_WIDTH = 854 // Maximum width in pixels
const ASPECT_RATIO = 16 / 9 // 16:9 aspect ratio
const DEFAULT_WIDTH = 988
const OVERLAY_ANIMATION_DURATION = 300 // Match CSS transition duration (0.3s)
const OVERLAY_TRIGGER_DELAY = 100 // Small delay to ensure story is rendered first
const OVERLAY_ANIMATION_TRIGGER_DELAY = 10 // Trigger slide-up animation after DOM update

interface StoryEndEventProps extends StoryEndEventPropsExtraProps {
    reason: string
    story_id: string
    story_title: string
    story_thumbnail_url: string
    story_type: StoryType
    time_spent_ms: number
    time_spent_seconds: number
    story_group_id: string
    story_group_title: string
    story_index: number
    group_length: number
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
    const [showOverlay, setShowOverlay] = useState(false)
    const [overlayComponent, setOverlayComponent] = useState<(() => JSX.Element) | null>(null)
    const [overlayAnimating, setOverlayAnimating] = useState(false)

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

    const sendStoryEndEvent = useCallback(
        (reason: string, extraProps?: StoryEndEventPropsExtraProps) => {
            const timeSpentMs = Date.now() - storyStartTimeRef.current
            const props: StoryEndEventProps = {
                reason: reason,
                story_id: activeGroup?.stories[activeStoryIndex].id,
                story_title: activeGroup?.stories[activeStoryIndex].title,
                story_thumbnail_url: activeGroup?.stories[activeStoryIndex].thumbnailUrl,
                story_type: activeGroup?.stories[activeStoryIndex].type,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
                story_index: activeStoryIndex,
                group_length: activeGroup?.stories.length || 0,
                time_spent_ms: timeSpentMs,
                time_spent_seconds: Math.round(timeSpentMs / 1000),
                story_watched_percentage:
                    activeStory?.durationMs && activeStory?.durationMs > 0
                        ? Math.round((timeSpentMs / activeStory.durationMs) * 100)
                        : undefined,
                ...extraProps,
            }
            posthog.capture('posthog_story_ended', props)
        },
        [activeGroup, activeStoryIndex, activeStory]
    )

    const handleClose = useCallback(
        (forceClose: boolean) => {
            const timeSpentMs = Date.now() - storyStartTimeRef.current

            sendStoryEndEvent(forceClose ? 'force_close' : 'natural_close')

            posthog.capture('posthog_story_closed', {
                reason: forceClose ? 'force_close' : 'natural_close',
                story_id: activeGroup?.stories[activeStoryIndex].id,
                story_title: activeGroup?.stories[activeStoryIndex].title,
                story_thumbnail_url: activeGroup?.stories[activeStoryIndex].thumbnailUrl,
                story_type: activeGroup?.stories[activeStoryIndex].type,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
                story_index: activeStoryIndex,
                group_length: activeGroup?.stories.length || 0,
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
            sendStoryEndEvent,
        ]
    )

    const handleStoryStart = useCallback(
        (index: number) => {
            storyStartTimeRef.current = Date.now()
            posthog.capture('posthog_story_started', {
                event: 'started',
                story_id: activeGroup?.stories[index].id,
                story_title: activeGroup?.stories[index].title,
                story_thumbnail_url: activeGroup?.stories[index].thumbnailUrl,
                story_type: activeGroup?.stories[index].type,
                story_group_id: activeGroup?.id,
                story_group_title: activeGroup?.title,
                story_index: index,
                group_length: activeGroup?.stories.length || 0,
            })
            setActiveStoryIndex(index)

            // Auto-trigger overlay for 'overlay' type stories
            const story = activeGroup?.stories[index]
            if (story?.type === StoryType.Overlay && story.seeMoreOverlay) {
                setTimeout(() => {
                    const closeHandler = (action?: CloseOverlayAction): void => {
                        setShowOverlay(false)
                        setOverlayComponent(null)
                        setIsPaused(false)
                        if (action === CloseOverlayAction.Modal) {
                            setOpenStoriesModal(false)
                        } else if (action === CloseOverlayAction.Next) {
                            // Go to next story
                            if (activeGroup && index < activeGroup.stories.length - 1) {
                                setActiveStoryIndex(index + 1)
                                return
                            }
                            // Last story in group - close the modal
                            setOpenStoriesModal(false)
                        } else if (action === CloseOverlayAction.Previous) {
                            // Go to previous story
                            if (index > 0) {
                                setActiveStoryIndex(index - 1)
                            }
                            // First story in group
                        }
                    }
                    setOverlayComponent(() => () => story.seeMoreOverlay!(closeHandler))
                    setShowOverlay(true)
                    setOverlayAnimating(true) // Start off-screen
                    setIsPaused(true)
                    // Trigger slide-up animation
                    setTimeout(() => setOverlayAnimating(false), OVERLAY_ANIMATION_TRIGGER_DELAY)
                }, OVERLAY_TRIGGER_DELAY)
            }
        },
        [setActiveStoryIndex, activeGroup, setOverlayComponent, setShowOverlay, setIsPaused, setOpenStoriesModal]
    )

    const handlePrevious = useCallback(() => {
        if (activeStoryIndex > 0) {
            sendStoryEndEvent('previous')
            setActiveStoryIndex(activeStoryIndex - 1)
            setIsPaused(false)
        }
    }, [activeStoryIndex, setActiveStoryIndex, sendStoryEndEvent])

    // Reset pause state when modal opens or story changes
    useEffect(() => {
        if (openStoriesModal) {
            setIsPaused(false)
        }
    }, [openStoriesModal])

    // Reset pause state when active story changes
    useEffect(() => {
        setIsPaused(false)
        setShowOverlay(false)
        setOverlayComponent(null)
        setOverlayAnimating(false)
    }, [activeStoryIndex, activeGroupIndex])

    // Handle overlay close
    const handleOverlayClose = useCallback(
        (action?: CloseOverlayAction) => {
            setOverlayAnimating(true)

            // Wait for slide-down animation to complete
            setTimeout(() => {
                setShowOverlay(false)
                setOverlayComponent(null)
                setOverlayAnimating(false)
                setIsPaused(false)

                if (action === CloseOverlayAction.Modal) {
                    sendStoryEndEvent('overlay_close_modal')
                    setOpenStoriesModal(false)
                } else if (action === CloseOverlayAction.Next) {
                    sendStoryEndEvent('overlay_next')
                    // Go to next story
                    if (activeStoryIndex < maxStoryIndex - 1) {
                        setActiveStoryIndex(activeStoryIndex + 1)
                        return
                    }
                    // Last story in group - close the modal
                    setOpenStoriesModal(false)
                } else if (action === CloseOverlayAction.Previous) {
                    sendStoryEndEvent('overlay_previous')
                    // Go to previous story
                    if (activeStoryIndex > 0) {
                        setActiveStoryIndex(activeStoryIndex - 1)
                    }
                    // First story in group
                }
            }, OVERLAY_ANIMATION_DURATION) // Match CSS transition duration
            // Default action 'overlay' or undefined just closes the overlay and continues current story
        },
        [setOpenStoriesModal, activeStoryIndex, maxStoryIndex, setActiveStoryIndex, sendStoryEndEvent]
    )

    if (!openStoriesModal || !activeGroup) {
        return null
    }

    const stories = activeGroup.stories.map(
        (story: story): Story => ({
            url: story.mediaUrl || '',
            type: story.type,
            duration: story.durationMs,
            header: {
                heading: story.title,
                subheading: story.description || '',
                profileImage: story.thumbnailUrl,
            },
            seeMore:
                story.seeMoreLink || story.seeMoreOverlay
                    ? () => {
                          sendStoryEndEvent('see_more')
                          if (story.seeMoreOverlay) {
                              setOverlayComponent(() => () => story.seeMoreOverlay!(handleOverlayClose))
                              setShowOverlay(true)
                              setOverlayAnimating(true) // Start off-screen
                              setIsPaused(true)
                              // Trigger slide-up animation
                              setTimeout(() => setOverlayAnimating(false), OVERLAY_ANIMATION_TRIGGER_DELAY)
                          } else if (story.seeMoreLink) {
                              window.open(story.seeMoreLink, '_blank')
                              setIsPaused(true)
                          }
                          return null
                      }
                    : undefined,
            seeMoreOptions: story.seeMoreOptions,
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
                <div className="relative flex-1 stories-container">
                    <StoriesPlayer
                        stories={stories}
                        defaultInterval={IMAGE_STORY_INTERVAL}
                        currentIndex={activeStoryIndex}
                        isPaused={isPaused}
                        width={dimensions.width}
                        height={dimensions.height}
                        onNext={() => {
                            if (!activeGroup?.stories[activeStoryIndex]) {
                                return
                            }
                            sendStoryEndEvent('next')
                            setIsPaused(false)

                            // Check if this is the last story in the current group
                            if (activeStoryIndex >= maxStoryIndex - 1) {
                                // Last story in group - close the modal
                                setOpenStoriesModal(false)
                            } else {
                                // Not last story - advance to next story in group
                                setActiveStoryIndex(activeStoryIndex + 1)
                            }
                        }}
                        onPrevious={() => {
                            setIsPaused(false)
                            handlePrevious()
                        }}
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
                        onPauseToggle={() => setIsPaused(!isPaused)}
                        onClose={() => handleClose(true)}
                    />

                    {/* Overlay Component */}
                    {(showOverlay || overlayAnimating) && overlayComponent && (
                        <div
                            className={`absolute inset-0 z-50 bg-white ${
                                overlayAnimating ? 'overlay-slide-down' : 'overlay-slide-up'
                            }`}
                        >
                            {!activeGroup?.stories[activeStoryIndex]?.seeMoreOptions?.hideDefaultClose && (
                                <button
                                    onClick={() => handleOverlayClose()}
                                    className="absolute top-4 right-4 z-10 bg-black/20 hover:bg-black/30 text-white rounded-full w-8 h-8 flex items-center justify-center transition-all duration-200 cursor-pointer"
                                    aria-label="Close overlay"
                                >
                                    <IconX className="w-5 h-5" />
                                </button>
                            )}
                            <div className="w-full h-full overflow-auto">{overlayComponent()}</div>
                        </div>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
