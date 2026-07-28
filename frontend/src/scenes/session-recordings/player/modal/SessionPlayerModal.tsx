import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { IconHeatmap } from 'lib/lemon-ui/icons'
import { buildRecordingMatchingEventFiltersForUrl } from 'scenes/heatmaps/components/heatmapRecordingFallbackLogic'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'

import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { sessionPlayerModalLogic } from './sessionPlayerModalLogic'

/**
 * When SessionPlayerModal is present in the page you can call `openSessionPlayer` action to open the modal
 * and play a given session
 *
 * It assumes it is only placed in the page once and lives in the GlobalModals component as a result
 * Adding it to the page more than once will cause weird playback behaviour
 *
 */
export function SessionPlayerModal(): JSX.Element | null {
    const { activeSessionRecording, modalContext } = useValues(sessionPlayerModalLogic())
    const { closeSessionPlayer } = useActions(sessionPlayerModalLogic())
    const isChoosingHeatmapBackground = modalContext?.type === 'heatmap-background-selection'

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
                        <LemonButton icon={<IconX />} size="small" onClick={closeSessionPlayer} tooltip="Close" />
                    </div>
                </div>
            )}
            <LemonModal.Content embedded>
                {activeSessionRecording?.id && <SessionRecordingPlayer {...logicProps} noBorder />}
            </LemonModal.Content>
        </LemonModal>
    )
}
