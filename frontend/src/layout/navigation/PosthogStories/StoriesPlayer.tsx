import { IconArrowRight } from '@posthog/icons'
import { useCallback, useEffect, useRef, useState } from 'react'

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
    width: string
    height: string
    currentIndex: number
    isPaused: boolean
    onNext: () => void
    onPrevious: () => void
    onAllStoriesEnd: () => void
    onStoryEnd: () => void
    onStoryStart: (index: number) => void
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
}: StoriesPlayerProps): JSX.Element => {
    const [progress, setProgress] = useState(0)
    const progressRef = useRef<number>(0)
    const intervalRef = useRef<NodeJS.Timeout | null>(null)
    const videoRef = useRef<HTMLVideoElement | null>(null)
    const progressBarRef = useRef<HTMLDivElement | null>(null)
    const startTimeRef = useRef<number>(0)
    const currentStory = stories[currentIndex]

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

            if (clickX < containerWidth / 2) {
                // Left side - previous
                if (currentIndex > 0) {
                    onPrevious()
                }
            } else {
                // Right side - next
                if (currentIndex < stories.length - 1) {
                    onNext()
                } else {
                    onAllStoriesEnd()
                }
            }
        },
        [currentIndex, stories.length, onNext, onPrevious, onAllStoriesEnd]
    )

    if (!currentStory) {
        return <div>No story to display</div>
    }

    return (
        <div className="relative bg-black rounded overflow-hidden cursor-pointer" onClick={handleContainerClick}>
            {/* Progress bars */}
            <div className="absolute top-2 left-2 right-2 flex gap-1 z-10">
                {stories.map((_, index) => (
                    <div key={index} className="flex-1 h-0.5 bg-white/30 rounded-full overflow-hidden">
                        <div
                            ref={index === currentIndex ? progressBarRef : null}
                            className={`h-full bg-white transition-all duration-100 ease-linear rounded-full ${
                                index === currentIndex ? 'progress-bar-active' : index < currentIndex ? 'w-full' : 'w-0'
                            }`}
                        />
                    </div>
                ))}
            </div>

            {/* Header */}
            {currentStory.header && (
                <div className="absolute top-6 left-2 right-2 flex items-center gap-2 z-10">
                    {currentStory.header.profileImage && (
                        <img
                            src={currentStory.header.profileImage}
                            alt="Profile"
                            className="w-8 h-8 rounded-full object-cover"
                        />
                    )}
                    <div className="flex-1 min-w-0">
                        <div className="text-white text-sm font-medium truncate">{currentStory.header.heading}</div>
                        {currentStory.header.subheading && (
                            <div className="text-white/80 text-xs truncate">{currentStory.header.subheading}</div>
                        )}
                    </div>
                </div>
            )}

            {/* Media content */}
            <div className="w-full h-full flex items-center justify-center">
                {currentStory.type === 'video' ? (
                    <video
                        ref={videoRef}
                        src={currentStory.url}
                        className="w-full h-full object-contain"
                        autoPlay
                        muted
                        playsInline
                        onEnded={handleVideoEnd}
                    />
                ) : (
                    <img src={currentStory.url} alt="Story content" className="w-full h-full object-contain" />
                )}
            </div>

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

            {/* Navigation zones (invisible) */}
            <div className="absolute inset-0 flex">
                <div className="w-1/2 h-full" />
                <div className="w-1/2 h-full" />
            </div>
        </div>
    )
}
