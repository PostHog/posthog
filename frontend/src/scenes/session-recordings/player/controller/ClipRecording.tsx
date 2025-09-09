import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { IconRecordingClip } from 'lib/lemon-ui/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ExporterFormat } from '~/types'

interface ClipTimes {
    current: string
    startClip: string
    endClip: string
}

function calculateClipTimes(currentTimeMs: number | null, sessionDurationMs: number, clipDuration: number): ClipTimes {
    const startTimeSeconds = (currentTimeMs ?? 0) / 1000
    const endTimeSeconds = Math.floor(sessionDurationMs / 1000)
    const fixedUnits = endTimeSeconds > 3600 ? 3 : 2

    const current = colonDelimitedDuration(startTimeSeconds, fixedUnits)

    // Calculate ideal start/end centered around current time
    let idealStart = startTimeSeconds - clipDuration / 2
    let idealEnd = startTimeSeconds + clipDuration / 2

    // Adjust if we hit the beginning boundary
    if (idealStart < 0) {
        idealStart = 0
        idealEnd = Math.min(clipDuration, endTimeSeconds)
    }

    // Adjust if we hit the end boundary
    if (idealEnd > endTimeSeconds) {
        idealEnd = endTimeSeconds
        idealStart = Math.max(0, endTimeSeconds - clipDuration)
    }

    const startClip = colonDelimitedDuration(idealStart, fixedUnits)
    const endClip = colonDelimitedDuration(idealEnd, fixedUnits)

    return { current, startClip, endClip }
}

export function ClipOverlay(): JSX.Element | null {
    const { currentPlayerTime, sessionPlayerData, showingClipParams } = useValues(sessionRecordingPlayerLogic)
    const { getClip, setShowingClipParams } = useActions(sessionRecordingPlayerLogic)
    const [duration, setDuration] = useState(5)
    const [format, setFormat] = useState(ExporterFormat.MP4)

    const { current, startClip, endClip } = calculateClipTimes(
        currentPlayerTime,
        sessionPlayerData.durationMs,
        duration
    )

    if (!showingClipParams) {
        return null
    }

    return (
        <div className="absolute bottom-4 right-4 z-20 w-64 space-y-3 p-2 bg-primary border border-border rounded shadow-lg">
            <div className="space-y-1 text-center">
                <div className="text-sm font-medium text-default">
                    Clipping from {startClip} to {endClip}
                </div>
                <div className="text-muted">(centered around {current})</div>
            </div>
            <div className="space-y-1">
                <label className="block text-sm font-medium text-default">Format</label>
                <LemonSegmentedButton
                    fullWidth
                    size="xsmall"
                    value={format}
                    onChange={(value) => setFormat(value)}
                    options={[
                        {
                            value: ExporterFormat.MP4,
                            label: 'MP4',
                            tooltip: 'Video file - higher quality, better for detailed analysis',
                            'data-attr': 'replay-screenshot-mp4',
                        },
                        {
                            value: ExporterFormat.GIF,
                            label: 'GIF',
                            tooltip: 'Animated GIF - smaller file size, good for sharing',
                            'data-attr': 'replay-screenshot-gif',
                        },
                    ]}
                />
            </div>

            <div className="space-y-1">
                <label className="block text-sm font-medium text-default">Duration (seconds)</label>
                <LemonSegmentedSelect
                    fullWidth
                    size="xsmall"
                    options={[
                        { value: 5, label: '5', 'data-attr': 'replay-clip-duration-5' },
                        { value: 10, label: '10', 'data-attr': 'replay-clip-duration-10' },
                        { value: 15, label: '15', 'data-attr': 'replay-clip-duration-15' },
                    ]}
                    value={duration}
                    onChange={(value) => setDuration(value)}
                />
            </div>

            <LemonButton
                onClick={() => {
                    getClip(format, duration)
                    setShowingClipParams(false)
                }}
                type="primary"
                className="mt-3 mx-auto"
                disabledReason={
                    !duration || duration < 5 || duration > 15 ? 'Duration must be between 5 and 15 seconds' : undefined
                }
                data-attr="replay-clip-create"
            >
                Create clip
            </LemonButton>
        </div>
    )
}

export function ClipRecording(): JSX.Element {
    const { showingClipParams, currentPlayerTime, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setShowingClipParams } = useActions(sessionRecordingPlayerLogic)

    const { current } = calculateClipTimes(currentPlayerTime, sessionPlayerData.durationMs, 5)

    return (
        <LemonButton
            size="xsmall"
            active={showingClipParams}
            onClick={() => {
                setPause()
                setShowingClipParams(!showingClipParams)
            }}
            tooltip={
                <div className="flex items-center gap-2">
                    <span>
                        Create clip around {current} <KeyboardShortcut x />
                    </span>
                    <LemonTag type="warning" size="small">
                        BETA
                    </LemonTag>
                </div>
            }
            icon={<IconRecordingClip className="text-xl" />}
            data-attr="replay-clip"
            tooltipPlacement="top"
        />
    )
}
