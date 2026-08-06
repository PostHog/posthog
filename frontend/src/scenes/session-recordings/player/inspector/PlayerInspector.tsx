import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { PlayerInspectorBottomSettings } from 'scenes/session-recordings/player/inspector/PlayerInspectorBottomSettings'
import { PlayerInspectorControls } from 'scenes/session-recordings/player/inspector/PlayerInspectorControls'
import { PlayerInspectorList } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerInspectorLogic } from './playerInspectorLogic'

function MatchingEventsCoverageWarning(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { matchingEventsOutsideRecordingWindow } = useValues(playerInspectorLogic(logicProps))

    // Only warn when the filter matched events but none of them fall within the playable window;
    // an unfiltered recording, or one with any in-window match, renders nothing here.
    if (!matchingEventsOutsideRecordingWindow) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mx-2 mb-1">
            The event matching your filter happened outside the time this recording covers, so there's nothing here to
            jump to. Other recordings in your results may cover it.
        </LemonBanner>
    )
}

export function PlayerInspector(): JSX.Element {
    return (
        <>
            <PlayerInspectorControls />
            <MatchingEventsCoverageWarning />
            <PlayerInspectorList />
            <PlayerInspectorBottomSettings />
        </>
    )
}
