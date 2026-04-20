import { useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconVideoCamera } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { sessionProfileLogic } from '../sessionProfileLogic'

export function SessionRecordingSection(): JSX.Element | null {
    const { sessionId, hasRecording, hasRecordingLoading } = useValues(sessionProfileLogic)
    const [isExpanded, setIsExpanded] = useState(true)

    return (
        <div id="session-recording-section">
            <LemonCard className="overflow-hidden p-0" hoverEffect={false}>
                <div
                    className="flex items-center gap-2 bg-surface-primary p-3 cursor-pointer hover:bg-surface-secondary"
                    onClick={() => setIsExpanded(!isExpanded)}
                >
                    <LemonButton
                        icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                        size="small"
                        onClick={(e) => {
                            e.stopPropagation()
                            setIsExpanded(!isExpanded)
                        }}
                    />
                    <IconVideoCamera className="text-muted-alt" />
                    <h3 className="text-lg font-semibold m-0">Session recording</h3>
                </div>

                {isExpanded && (
                    <div className="border-t border-border">
                        {hasRecordingLoading ? (
                            <div className="flex justify-center items-center h-[300px]">
                                <Spinner />
                            </div>
                        ) : hasRecording ? (
                            <div className="h-[400px]">
                                <SessionRecordingPlayer
                                    sessionRecordingId={sessionId}
                                    playerKey={`session-profile-${sessionId}`}
                                    mode={SessionRecordingPlayerMode.Standard}
                                    autoPlay={false}
                                    noMeta
                                    noBorder
                                    withSidebar={false}
                                />
                            </div>
                        ) : (
                            <div className="flex flex-col items-center justify-center h-[200px] text-muted-alt">
                                <IconVideoCamera className="text-4xl mb-2 opacity-50" />
                                <p className="m-0">No recording available for this session</p>
                            </div>
                        )}
                    </div>
                )}
            </LemonCard>
        </div>
    )
}
