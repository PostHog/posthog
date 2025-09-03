import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDropdown, LemonInput, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { IconRecordingClip } from 'lib/lemon-ui/icons'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { ExporterFormat } from '~/types'

function ClipParams(): JSX.Element {
    const { getClip, setShowingClipParams } = useActions(sessionRecordingPlayerLogic)
    const [duration, setDuration] = useState(5)
    const [format, setFormat] = useState(ExporterFormat.GIF)

    return (
        <div className="space-y-3 p-2 min-w-64">
            <div className="space-y-1">
                <label className="block text-sm font-medium text-default">Format</label>
                <LemonSegmentedButton
                    fullWidth
                    size="xsmall"
                    value={format}
                    onChange={(value) => setFormat(value)}
                    options={[
                        {
                            value: ExporterFormat.GIF,
                            label: 'GIF',
                            tooltip: 'Animated GIF - smaller file size, good for sharing',
                        },
                        {
                            value: ExporterFormat.MP4,
                            label: 'MP4',
                            tooltip: 'Video file - higher quality, better for detailed analysis',
                        },
                    ]}
                />
            </div>

            <div className="space-y-1">
                <label className="block text-sm font-medium text-default">Duration (seconds)</label>
                <LemonInput
                    type="number"
                    value={duration}
                    onChange={(value) => setDuration(value ?? 5)}
                    min={5}
                    max={30}
                    placeholder="5"
                />
                <div className="text-xs text-muted">Between 5 and 30 seconds</div>
            </div>

            <LemonButton
                onClick={() => {
                    getClip(format, duration)
                    setShowingClipParams(false)
                }}
                type="primary"
                className="mt-3 mx-auto"
                disabledReason={
                    !duration || duration < 5 || duration > 30 ? 'Duration must be between 5 and 30 seconds' : undefined
                }
            >
                Create clip
            </LemonButton>
        </div>
    )
}

export function ClipRecording(): JSX.Element {
    const { showingClipParams } = useValues(sessionRecordingPlayerLogic)
    const { setPause, setShowingClipParams } = useActions(sessionRecordingPlayerLogic)

    return (
        <LemonDropdown
            overlay={<ClipParams />}
            placement="bottom-end"
            visible={showingClipParams}
            closeOnClickInside={false}
            onClickOutside={() => {
                setShowingClipParams(!showingClipParams)
            }}
            onVisibilityChange={(visible) => {
                setShowingClipParams(visible)
            }}
        >
            <LemonButton
                size="xsmall"
                onClick={() => {
                    setPause(true)
                    setShowingClipParams(!showingClipParams)
                }}
                tooltip={
                    <div className="flex items-center gap-2">
                        <span>
                            Get a clip around this point of the recording <KeyboardShortcut x />
                        </span>
                        <LemonTag type="warning" size="small">
                            BETA
                        </LemonTag>
                    </div>
                }
                icon={<IconRecordingClip className="text-xl" />}
                data-attr="replay-screenshot-gif"
                tooltipPlacement="top"
            />
        </LemonDropdown>
    )
}
