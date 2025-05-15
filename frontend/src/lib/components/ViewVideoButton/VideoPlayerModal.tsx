import { IconPauseFilled, IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useEffect, useRef, useState } from 'react'

import { EventType } from '~/types'

// Define VideoStreamPlayer interface for TypeScript
declare global {
    interface Window {
        VideoStreamPlayer?: {
            loadVideo: (videoUrl: string) => void
        }
    }
}

interface VideoPlayerModalProps {
    isOpen: boolean
    onClose: () => void
    event?: EventType
}

export function VideoPlayerModal({ isOpen, onClose, event }: VideoPlayerModalProps): JSX.Element {
    const videoRef = useRef<HTMLVideoElement>(null)
    const [isPlaying, setIsPlaying] = useState(false)
    const [currentTime, setCurrentTime] = useState(0)
    const [duration, setDuration] = useState(0)
    const videoUrl = event?.properties?.video_clip

    // Reset state when modal opens
    useEffect(() => {
        if (isOpen) {
            setIsPlaying(false)
            setCurrentTime(0)

            // Send video_clip property to VideoStreamPlayer when modal opens
            if (event?.properties?.video_clip && window.VideoStreamPlayer) {
                window.VideoStreamPlayer.loadVideo(event.properties.video_clip)
            }
        }
    }, [isOpen, event])

    // Handle play/pause
    const togglePlay = (): void => {
        if (!videoRef.current) {
            return
        }

        if (isPlaying) {
            videoRef.current.pause()
        } else {
            void videoRef.current.play()
        }
        setIsPlaying(!isPlaying)
    }

    // Handle time update
    const handleTimeUpdate = (): void => {
        if (!videoRef.current) {
            return
        }
        setCurrentTime(videoRef.current.currentTime)
    }

    // Handle seeking
    const handleSeek = (value: number): void => {
        if (!videoRef.current) {
            return
        }
        videoRef.current.currentTime = value
        setCurrentTime(value)
    }

    // Handle video metadata loaded
    const handleLoadedMetadata = (): void => {
        if (!videoRef.current) {
            return
        }
        setDuration(videoRef.current.duration)
    }

    // Format time in MM:SS
    const formatTime = (timeInSeconds: number): string => {
        const minutes = Math.floor(timeInSeconds / 60)
        const seconds = Math.floor(timeInSeconds % 60)
        return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Event Video"
            width={800}
            footer={
                <div className="flex justify-end">
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="relative w-full aspect-video bg-black rounded overflow-hidden">
                    {videoUrl ? (
                        <video
                            ref={videoRef}
                            className="w-full h-full object-contain"
                            src={videoUrl}
                            onTimeUpdate={handleTimeUpdate}
                            onLoadedMetadata={handleLoadedMetadata}
                            onEnded={() => setIsPlaying(false)}
                        />
                    ) : (
                        <div className="flex items-center justify-center h-full text-muted">
                            No video available for this event
                        </div>
                    )}
                </div>

                {/* Video Controls */}
                {videoUrl && (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-2">
                            <LemonButton
                                icon={isPlaying ? <IconPauseFilled /> : <IconPlayFilled />}
                                type="secondary"
                                size="small"
                                onClick={togglePlay}
                            >
                                {isPlaying ? 'Pause' : 'Play'}
                            </LemonButton>
                            <span className="text-sm text-muted">
                                {formatTime(currentTime)} / {formatTime(duration)}
                            </span>
                        </div>

                        <LemonSlider
                            value={currentTime}
                            onChange={handleSeek}
                            min={0}
                            max={duration || 100}
                            step={0.1}
                        />
                    </div>
                )}

                {/* Event Details */}
                {event && (
                    <div className="mt-4 pt-4 border-t">
                        <h3 className="text-base font-semibold mb-2">Event Details</h3>
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <tbody>
                                    <tr>
                                        <td className="font-medium pr-4 py-1">Event</td>
                                        <td>{event.event}</td>
                                    </tr>
                                    <tr>
                                        <td className="font-medium pr-4 py-1">Timestamp</td>
                                        <td>{event.timestamp}</td>
                                    </tr>
                                    <tr>
                                        <td className="font-medium pr-4 py-1">Distinct ID</td>
                                        <td>{event.distinct_id}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
