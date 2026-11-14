import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { IconHeatmap } from 'lib/lemon-ui/icons'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { buildRecordingMatchingEventFiltersForUrl } from 'products/web_analytics/frontend/heatmaps/components/heatmapRecordingFallbackLogic'

import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { SessionPlayerModalRecordingList, sessionPlayerModalLogic } from './sessionPlayerModalLogic'

/**
 * When SessionPlayerModal is present in the page you can call `openSessionPlayer` action to open the modal
 * and play a given session
 *
 * It assumes it is only placed in the page once and lives in the GlobalModals component as a result
 * Adding it to the page more than once will cause weird playback behaviour
 *
 */
export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording, modalContext, recordingList, hasNextRecordingInList, showRecordingListPosition } =
        useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer, playNextRecordingInList } = useActions(sessionPlayerModalLogic())
    const isChoosingHeatmapBackground = modalContext?.type === 'heatmap-background-selection'
    // The modal builds and mounts the player logic before SessionRecordingPlayer renders, so the logic only sees
    // the player element at mount when the modal owns the ref and passes it in.
    const playerRef = useRef<HTMLDivElement>(null)

    // activeSessionRecording?.matching_events should always be a single element array
    // but, we're filtering and using flatMap just in case
    const matchedEvents =
        activeSessionRecording?.matching_events
            ?.filter((matchingEvents) => {
                return matchingEvents.session_id === activeSessionRecording?.id
            })
            .flatMap((matchedRecording) => matchedRecording.events) || []

    const logicProps: SessionRecordingPlayerLogicProps = {
        playerKey: 'modal',
        sessionRecordingId: activeSessionRecording?.id || '',
        autoPlay: !isChoosingHeatmapBackground,
        matchingEventsMatchType: isChoosingHeatmapBackground
            ? {
                  matchType: 'backend',
                  filters: buildRecordingMatchingEventFiltersForUrl(modalContext.targetUrl),
              }
            : {
                  matchType: 'uuid',
                  matchedEvents: matchedEvents,
              },
        skipToFirstMatchingEvent: isChoosingHeatmapBackground,
        playNextRecording: hasNextRecordingInList ? () => playNextRecordingInList() : undefined,
        playerRef,
        keepFullScreenAcrossRecordings: true,
    }

    const playerLogic = sessionRecordingPlayerLogic(logicProps)
    const { isFullScreen, resolution, rootFrame } = useValues(playerLogic)
    const { openHeatmap } = useActions(playerLogic)

    return (
        <LemonModal
            isOpen={!!activeSessionRecording}
            onClose={closeSessionPlayer}
            simple
            title=""
            width={1600}
            fullScreen={isFullScreen}
            closable={!isFullScreen}
            hideCloseButton
            zIndex="1161"
        >
            {!isFullScreen && (
                <div className="flex items-center justify-between gap-4 border-b bg-surface-primary px-3 py-2">
                    {isChoosingHeatmapBackground ? (
                        <div>
                            <h3 className="mb-0">Choose the background</h3>
                            <p className="mb-0 text-sm text-muted">
                                The player pauses at the first matching page event. Scrub to the exact state you want,
                                then use that moment as the heatmap background.
                            </p>
                        </div>
                    ) : showRecordingListPosition && recordingList ? (
                        <RecordingListPosition recordingList={recordingList} />
                    ) : (
                        <span />
                    )}
                    <div className="flex items-center gap-2 shrink-0">
                        {isChoosingHeatmapBackground ? (
                            <LemonButton
                                type="primary"
                                icon={<IconHeatmap />}
                                onClick={openHeatmap}
                                disabledReason={
                                    !rootFrame || !resolution ? 'Wait for the recording to load' : undefined
                                }
                                data-attr="heatmap-use-recording-moment"
                            >
                                Use this moment as background
                            </LemonButton>
                        ) : null}
                        <LemonButton
                            data-attr="player-modal-close"
                            icon={<IconX />}
                            size="small"
                            onClick={closeSessionPlayer}
                            tooltip="Close"
                        />
                    </div>
                </div>
            )}
            <LemonModal.Content embedded>
                {activeSessionRecording?.id && <SessionRecordingPlayer {...logicProps} noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}

function RecordingListPosition({ recordingList }: { recordingList: SessionPlayerModalRecordingList }): JSX.Element {
    const { entries, position, hasMoreToLoad } = recordingList
    const personDisplayName = entries[position]?.personDisplayName
    return (
        <div className="flex items-center gap-1 min-w-0 text-sm">
            <span className="font-semibold shrink-0">
                {`Recording ${position + 1} of ${entries.length}${hasMoreToLoad ? ' loaded' : ''}`}
            </span>
            {personDisplayName ? <span className="truncate text-secondary">{`· ${personDisplayName}`}</span> : null}
        </div>
    )
}
