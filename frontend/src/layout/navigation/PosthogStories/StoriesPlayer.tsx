import { IconArrowRight, IconChevronLeft, IconChevronRight, IconPauseFilled, IconX } from '@posthog/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import React from 'react'

export interface Story {
    url: string
    type: 'image' | 'video'
    duration?: number // Duration in milliseconds
    header?: {
        heading: string
        subheading: string
        profileImage: string
    }
    seeMore?: () => JSX.Element | null
    preloadResource?: boolean
}

export interface StoriesPlayerProps {
    stories: Story[]
    defaultInterval: number
    currentIndex: number
    isPaused: boolean
    onNext: () => void
    onPrevious: () => void
    onAllStoriesEnd: () => void
    onStoryEnd: () => void
    onStoryStart: (index: number) => void
    onPauseToggle: () => void
    onClose: () => void
    width: number
    height: number
}

interface ProgressBarProps {
    story: Story
    isCurrentStory: boolean
    isCompletedStory: boolean
    isPaused: boolean
    videoDuration: number | null
    defaultInterval: number
    animationKey: number
    onAnimationEnd?: () => void
}

const ProgressBar = ({
    story,
    isCurrentStory,
    isCompletedStory,
    isPaused,
    videoDuration,
    defaultInterval,
    animationKey,
    onAnimationEnd,
}: ProgressBarProps): JSX.Element => {
    const progressRef = useRef<HTMLDivElement>(null)

    // Calculate duration for this story
    const getDuration = (): number => {
        if (story.type === 'video' && isCurrentStory && videoDuration) {
            return videoDuration
        }
        return story.duration || defaultInterval
    }

    // Set CSS custom property for duration
    useEffect(() => {
        if (progressRef.current && isCurrentStory) {
            const duration = getDuration()
            progressRef.current.style.setProperty('--duration', `${duration}ms`)
        }
    }, [isCurrentStory, videoDuration, story, defaultInterval])

    // Determine progress bar state classes
    const getProgressBarClasses = (): string => {
        const baseClasses = 'h-full bg-white rounded-full'

        if (isCurrentStory) {
            return `${baseClasses} progress-bar-active ${isPaused ? 'progress-bar-paused' : ''}`
        } else if (isCompletedStory) {
            return `${baseClasses} w-full`
        }
        return `${baseClasses} w-0`
    }

    return (
        <div className="flex-1 h-0.75 bg-white/[0.45] rounded-full overflow-hidden">
            <div
                ref={progressRef}
                key={isCurrentStory ? `${animationKey}-progress` : 'progress'}
                className={getProgressBarClasses()}
                onAnimationEnd={onAnimationEnd}
            />
        </div>
    )
}

export const StoriesPlayer = ({
    stories,
    defaultInterval,
    currentIndex,
    isPaused,
    onNext,
    onPrevious,
    onAllStoriesEnd,
    onStoryEnd,
    onStoryStart,
    onPauseToggle,
    onClose,
    width,
    height,
}: StoriesPlayerProps): JSX.Element => {
    const [hoveredZone, setHoveredZone] = useState<'left' | 'right' | null>(null)
    const [videoDuration, setVideoDuration] = useState<number | null>(null)
    const [animationKey, setAnimationKey] = useState(0) // Force re-render when story changes
    const videoRef = useRef<HTMLVideoElement | null>(null)
    const currentStory = stories[currentIndex]
    const containerRef = useRef<HTMLDivElement>(null)

    // Reset when story changes
    useEffect(() => {
        setVideoDuration(null) // Reset video duration
        setAnimationKey((prev) => prev + 1) // Force animation restart
        onStoryStart(currentIndex)
    }, [currentIndex, onStoryStart])

    // Handle video duration loaded
    const handleVideoLoadedMetadata = useCallback(() => {
        if (videoRef.current && currentStory?.type === 'video') {
            setVideoDuration(videoRef.current.duration * 1000) // Convert to milliseconds
        }
    }, [currentStory])

    // Handle animation end for image stories
    const handleAnimationEnd = useCallback(() => {
        if (currentStory?.type === 'image') {
            onStoryEnd()
            if (currentIndex < stories.length - 1) {
                onNext()
            } else {
                onAllStoriesEnd()
            }
        }
    }, [currentStory, currentIndex, stories.length, onNext, onStoryEnd, onAllStoriesEnd])

    // Handle video pause/play
    useEffect(() => {
        if (currentStory?.type === 'video' && videoRef.current) {
            if (isPaused) {
                videoRef.current.pause()
            } else {
                void videoRef.current.play()
            }
        }
    }, [isPaused, currentStory])

    // Handle video end
    const handleVideoEnd = useCallback(() => {
        onStoryEnd()
        if (currentIndex < stories.length - 1) {
            onNext()
        } else {
            onAllStoriesEnd()
        }
    }, [currentIndex, stories.length, onNext, onStoryEnd, onAllStoriesEnd])

    // Handle click navigation
    const handleContainerClick = useCallback(
        (e: React.MouseEvent) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const clickX = e.clientX - rect.left
            const containerWidth = rect.width
            const fifthWidth = containerWidth / 5

            if (clickX < fifthWidth) {
                // Left 20% - previous
                if (currentIndex > 0) {
                    onPrevious()
                }
            } else if (clickX > containerWidth - fifthWidth) {
                // Right 20% - next (only if not last story)
                if (currentIndex < stories.length - 1) {
                    onNext()
                }
            } else {
                // Middle 60% - pause/play
                onPauseToggle()
            }
        },
        [currentIndex, stories.length, onNext, onPrevious, onPauseToggle]
    )

    if (!currentStory) {
        return <div>No story to display</div>
    }

    return (
        <div
            ref={containerRef}
            className="relative rounded overflow-hidden select-none"
            onClick={handleContainerClick}
            style={{ width, height }} // eslint-disable-line react/forbid-dom-props
        >
            {/* header wrapper with gradient */}
            <div className="absolute top-0 left-0 right-0 z-10 pt-3 px-3 pb-4 bg-gradient-to-b from-black/25 to-transparent">
                {/* Progress bars */}
                <div className="flex gap-1 mb-2">
                    {stories.map((story, index) => {
                        const isCurrentStory = index === currentIndex
                        const isCompletedStory = index < currentIndex

                        return (
                            <ProgressBar
                                key={index}
                                story={story}
                                isCurrentStory={isCurrentStory}
                                isCompletedStory={isCompletedStory}
                                isPaused={isPaused}
                                videoDuration={videoDuration}
                                defaultInterval={defaultInterval}
                                animationKey={animationKey}
                                onAnimationEnd={isCurrentStory ? handleAnimationEnd : undefined}
                            />
                        )
                    })}
                </div>

                {/* Header section with relative positioning for buttons */}
                <div className="relative rounded-lg px-1">
                    {/* Play/pause and close buttons - positioned in top right of header */}
                    <div className="absolute top-1 right-1 flex gap-2 z-10">
                        <button
                            onClick={(e) => {
                                e.stopPropagation()
                                e.preventDefault()
                                onClose()
                            }}
                            className="text-white hover:text-gray-200 w-8 h-8 flex items-center justify-center transition-all duration-200 cursor-pointer"
                            title="Close stories"
                        >
                            <IconX className="w-5 h-5 [&>*]:fill-white" />
                        </button>
                    </div>

                    {/* Header content */}
                    <div className="flex items-center gap-3 pr-20">
                        {currentStory.header ? (
                            <div className="flex items-center gap-3 flex-1 min-w-0">
                                {currentStory.header.profileImage && (
                                    <img
                                        src={currentStory.header.profileImage}
                                        alt="Profile"
                                        className="w-10 h-10 rounded-full object-cover"
                                    />
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className="text-white text-sm font-semibold truncate drop-shadow-lg">
                                        {currentStory.header.heading}
                                    </div>
                                    {currentStory.header.subheading && (
                                        <div className="text-white text-xs truncate drop-shadow-md">
                                            {currentStory.header.subheading}
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <div className="flex-1" />
                        )}
                    </div>
                </div>
            </div>

            {/* Media content */}
            <div className="w-full h-full flex items-center justify-center">
                {currentStory.type === 'video' ? (
                    <video
                        ref={videoRef}
                        src={currentStory.url}
                        className="w-full h-full object-contain rounded"
                        autoPlay
                        playsInline
                        onEnded={handleVideoEnd}
                        onLoadedMetadata={handleVideoLoadedMetadata}
                    />
                ) : (
                    <img src={currentStory.url} alt="Story content" className="w-full h-full object-cover" />
                )}
            </div>

            {/* Pause icon overlay */}
            {isPaused && (
                <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
                    <div className="bg-black/50 rounded-full w-12 h-12 flex items-center justify-center backdrop-blur-sm">
                        <IconPauseFilled className="w-4 h-4 text-white flex-shrink-0 aspect-square" />
                    </div>
                </div>
            )}

            {/* See More button */}
            {currentStory.seeMore && (
                <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 z-10">
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            currentStory.seeMore?.()
                        }}
                        className="flex items-center gap-2 bg-white/20 hover:bg-white/30 text-white px-4 py-2 rounded-full text-sm font-medium transition-all duration-200"
                        role="button"
                        aria-label="See more about this story - swipe up for more"
                    >
                        <span>See More</span>
                        <IconArrowRight className="w-4 h-4" />
                    </button>
                </div>
            )}

            {/* Navigation zones with arrows */}
            <div className="absolute inset-0 flex">
                {/* LEFT NAVIGATION ZONE */}
                {/* Only shows navigation if there's a previous story to go to */}
                <div
                    className={`w-1/5 h-full relative flex items-center justify-start pl-4 ${
                        currentIndex > 0 ? 'cursor-pointer' : ''
                    }`}
                    onMouseEnter={() => setHoveredZone('left')}
                    onMouseLeave={() => setHoveredZone(null)}
                >
                    {/* Previous story button - only visible when hovering and navigation is possible */}
                    {currentIndex > 0 && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation()
                                e.preventDefault()
                                onPrevious()
                            }}
                            onMouseDown={(e) => e.preventDefault()}
                            className={`text-white rounded-full w-8 h-8 flex items-center justify-center transition-all duration-200 z-10 bg-black/30 cursor-pointer select-none ${
                                hoveredZone === 'left' ? 'opacity-100' : 'opacity-0'
                            }`}
                            title="Previous story"
                        >
                            <IconChevronLeft className="w-5 h-5" />
                        </button>
                    )}
                </div>

                {/* MIDDLE ZONE - Clears hover state and allows pause/play functionality */}
                {/* When user hovers over middle, it clears hoveredZone so navigation arrows hide */}
                <div className="w-3/5 h-full" onMouseEnter={() => setHoveredZone(null)} />

                {/* RIGHT NAVIGATION ZONE */}
                {/* Only shows navigation if there's a next story to go to */}
                <div
                    className={`w-1/5 h-full relative flex items-center justify-end pr-4 ${
                        currentIndex < stories.length - 1 ? 'cursor-pointer' : ''
                    }`}
                    onMouseEnter={() => setHoveredZone('right')}
                    onMouseLeave={() => setHoveredZone(null)}
                >
                    {/* Next story button - only visible when hovering and navigation is possible */}
                    {currentIndex < stories.length - 1 && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation()
                                e.preventDefault()
                                onNext()
                            }}
                            onMouseDown={(e) => e.preventDefault()}
                            className={`text-white rounded-full w-8 h-8 flex items-center justify-center transition-all duration-200 z-10 bg-black/30 cursor-pointer select-none ${
                                hoveredZone === 'right' ? 'opacity-100' : 'opacity-0'
                            }`}
                            title="Next story"
                        >
                            <IconChevronRight className="w-5 h-5" />
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}
