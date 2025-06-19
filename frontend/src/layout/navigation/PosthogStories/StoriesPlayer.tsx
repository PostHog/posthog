import { IconArrowRight, IconChevronLeft, IconChevronRight, IconPauseFilled, IconX } from '@posthog/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import React from 'react'

export interface Story {
    url: string
    type: 'image' | 'video'
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
    const [progress, setProgress] = useState(0)
    const [hoveredZone, setHoveredZone] = useState<'left' | 'right' | null>(null)
    const progressRef = useRef<number>(0)
    const intervalRef = useRef<NodeJS.Timeout | null>(null)
    const videoRef = useRef<HTMLVideoElement | null>(null)
    const progressBarRef = useRef<HTMLDivElement | null>(null)
    const startTimeRef = useRef<number>(0)
    const currentStory = stories[currentIndex]
    const containerRef = useRef<HTMLDivElement>(null)

    // Reset progress when story changes
    useEffect(() => {
        setProgress(0)
        progressRef.current = 0
        startTimeRef.current = Date.now()
        onStoryStart(currentIndex)
    }, [currentIndex, onStoryStart])

    // Update progress bar width via DOM manipulation
    useEffect(() => {
        if (progressBarRef.current) {
            progressBarRef.current.style.width = `${progress}%`
        }
    }, [progress])

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

    // Handle progress for images and videos
    useEffect(() => {
        if (isPaused) {
            if (intervalRef.current) {
                clearInterval(intervalRef.current)
                intervalRef.current = null
            }
            return
        }

        if (currentStory?.type === 'video') {
            // For videos, use video duration
            const video = videoRef.current
            if (video && video.duration) {
                const updateProgress = (): void => {
                    if (video.currentTime && video.duration) {
                        const newProgress = (video.currentTime / video.duration) * 100
                        setProgress(newProgress)
                        progressRef.current = newProgress
                    }
                }

                video.addEventListener('timeupdate', updateProgress)
                return () => video.removeEventListener('timeupdate', updateProgress)
            }
        } else {
            // For images, use timer
            const startTime = Date.now()
            intervalRef.current = setInterval(() => {
                const elapsed = Date.now() - startTime
                const newProgress = Math.min((elapsed / defaultInterval) * 100, 100)
                setProgress(newProgress)
                progressRef.current = newProgress

                if (newProgress >= 100) {
                    onStoryEnd()
                    if (currentIndex < stories.length - 1) {
                        onNext()
                    } else {
                        onAllStoriesEnd()
                    }
                }
            }, 50)
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }
    }, [currentIndex, isPaused, currentStory, defaultInterval, onNext, onStoryEnd, onAllStoriesEnd, stories.length])

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
            className="relative rounded overflow-hidden"
            onClick={handleContainerClick}
            style={{ width, height }} // eslint-disable-line react/forbid-dom-props
        >
            {/* Progress bars and header wrapper with gradient */}
            <div className="absolute top-0 left-0 right-0 z-10 p-2 bg-gradient-to-b from-black/20 to-transparent">
                {/* Progress bars */}
                <div className="flex gap-1 mb-2">
                    {stories.map((_, index) => (
                        <div key={index} className="flex-1 h-0.75 bg-white/[0.45] rounded-full overflow-hidden">
                            <div
                                ref={index === currentIndex ? progressBarRef : null}
                                className={`h-full bg-white transition-all duration-100 ease-linear rounded-full ${
                                    index === currentIndex
                                        ? 'progress-bar-active'
                                        : index < currentIndex
                                        ? 'w-full'
                                        : 'w-0'
                                }`}
                            />
                        </div>
                    ))}
                </div>

                {/* Header section with relative positioning for buttons */}
                <div className="relative rounded-lg p-2">
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
                                        className="w-10 h-10 rounded-full object-cover ring-2 ring-white shadow-lg"
                                    />
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className="text-white text-sm font-semibold truncate">
                                        {currentStory.header.heading}
                                    </div>
                                    {currentStory.header.subheading && (
                                        <div className="text-white text-xs truncate">
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
                        muted
                        playsInline
                        onEnded={handleVideoEnd}
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
                <div
                    className={`w-1/6 h-full relative flex items-center justify-start pl-4 ${
                        currentIndex > 0 ? 'cursor-pointer' : ''
                    }`}
                    onMouseEnter={() => setHoveredZone('left')}
                    onMouseLeave={() => setHoveredZone(null)}
                >
                    {currentIndex > 0 && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation()
                                onPrevious()
                            }}
                            className={`text-white rounded-full w-8 h-8 flex items-center justify-center transition-all duration-200 z-10 bg-black/30 ${
                                hoveredZone === 'left' ? 'opacity-100' : 'opacity-50'
                            }`}
                            title="Previous story"
                        >
                            <IconChevronLeft className="w-5 h-5" />
                        </button>
                    )}
                </div>
                <div className="w-4/6 h-full" onMouseEnter={() => setHoveredZone(null)} />
                <div
                    className={`w-1/6 h-full relative flex items-center justify-end pr-4 ${
                        currentIndex < stories.length - 1 ? 'cursor-pointer' : ''
                    }`}
                    onMouseEnter={() => setHoveredZone('right')}
                    onMouseLeave={() => setHoveredZone(null)}
                >
                    {currentIndex < stories.length - 1 && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation()
                                onNext()
                            }}
                            className={`text-white rounded-full w-8 h-8 flex items-center justify-center transition-all duration-200 z-10 bg-black/30 ${
                                hoveredZone === 'right' ? 'opacity-100' : 'opacity-40'
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
