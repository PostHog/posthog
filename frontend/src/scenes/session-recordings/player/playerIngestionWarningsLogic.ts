import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import {
    IngestionWarning,
    IngestionWarningSummary,
} from 'scenes/data-management/ingestion-warnings/ingestionWarningsLogic'
import { projectLogic } from 'scenes/projectLogic'

import type { playerIngestionWarningsLogicType } from './playerIngestionWarningsLogicType'

/** Warning types meaning replay data was dropped, mapped to their banner phrase. */
export const REPLAY_INGESTION_WARNING_PHRASES: Record<string, string> = {
    replay_message_too_large: 'some data was too large to ingest',
    replay_session_rate_limited: 'the session exceeded the event rate limit',
    replay_message_invalid: 'some data was rejected as invalid',
}

/** Phrase for a replay-drop warning type, else undefined. Own-property check keeps forged types like `constructor` out. */
function replayWarningPhrase(type: string): string | undefined {
    return Object.hasOwn(REPLAY_INGESTION_WARNING_PHRASES, type) ? REPLAY_INGESTION_WARNING_PHRASES[type] : undefined
}

/** Session id of a replay warning: too_large nests it under replayRecord, others use sessionId. */
function warningSessionId(warning: IngestionWarning): string | undefined {
    return warning.details?.replayRecord?.session_id ?? warning.details?.sessionId
}

export interface PlayerIngestionWarningsLogicProps {
    sessionRecordingId: string
}

export const playerIngestionWarningsLogic = kea<playerIngestionWarningsLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'playerIngestionWarningsLogic', key]),
    props({} as PlayerIngestionWarningsLogicProps),
    key((props) => props.sessionRecordingId),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    loaders(({ props, values }) => ({
        replayWarnings: [
            [] as IngestionWarning[],
            {
                loadReplayWarnings: async () => {
                    if (!props.sessionRecordingId) {
                        return []
                    }
                    const { results } = await api.get(
                        `api/projects/${values.currentProjectId}/ingestion_warnings?q=${encodeURIComponent(
                            props.sessionRecordingId
                        )}`
                    )
                    return (results as IngestionWarningSummary[])
                        .filter((summary) => replayWarningPhrase(summary.type) !== undefined)
                        .flatMap((summary) => summary.warnings)
                        .filter((warning) => warningSessionId(warning) === props.sessionRecordingId)
                },
            },
        ],
    })),

    selectors({
        droppedDataPhrases: [
            (s) => [s.replayWarnings],
            (replayWarnings: IngestionWarning[]): string[] =>
                Array.from(new Set(replayWarnings.map((warning) => replayWarningPhrase(warning.type)))).filter(
                    (phrase): phrase is string => phrase !== undefined
                ),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadReplayWarnings()
    }),
])
