import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { experimentsSessionContextRetrieve } from 'products/experiments/frontend/generated/api'
import type {
    ExperimentSessionContextItemApi,
    ExperimentSessionContextResponseApi,
} from 'products/experiments/frontend/generated/api.schemas'

import type { sessionRecordingExperimentContextLogicType } from './sessionRecordingExperimentContextLogicType'

export interface SessionRecordingExperimentContextLogicProps {
    sessionRecordingId: string
}

export const sessionRecordingExperimentContextLogic = kea<sessionRecordingExperimentContextLogicType>([
    path((key) => [
        'scenes',
        'session-recordings',
        'player',
        'player-meta',
        'sessionRecordingExperimentContextLogic',
        key,
    ]),
    props({} as SessionRecordingExperimentContextLogicProps),
    key((props: SessionRecordingExperimentContextLogicProps) => props.sessionRecordingId),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], teamLogic, ['currentProjectId']],
    })),
    loaders(({ props, values }) => ({
        experimentContext: [
            null as ExperimentSessionContextResponseApi | null,
            {
                loadExperimentContext: async () => {
                    if (!values.featureFlags[FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT] || !props.sessionRecordingId) {
                        return null
                    }
                    try {
                        return await experimentsSessionContextRetrieve(String(values.currentProjectId), {
                            session_id: props.sessionRecordingId,
                        })
                    } catch {
                        // A 404 just means the recording has no queryable metadata (yet) — show nothing.
                        return null
                    }
                },
            },
        ],
    })),
    selectors({
        experimentItems: [
            (s) => [s.experimentContext],
            (experimentContext): ExperimentSessionContextItemApi[] => experimentContext?.results ?? [],
        ],
        hasExperimentContext: [(s) => [s.experimentItems], (experimentItems): boolean => experimentItems.length > 0],
        hasMultipleVariantWarning: [
            (s) => [s.experimentItems],
            (experimentItems): boolean => experimentItems.some((item) => item.multiple_variants),
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadExperimentContext()
    }),
])
