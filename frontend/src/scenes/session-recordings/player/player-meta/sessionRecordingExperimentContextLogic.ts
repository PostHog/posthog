import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

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

export function isControlVariant(item: ExperimentSessionContextItemApi): boolean {
    return item.variant.toLowerCase() === 'control'
}

// Lower rank sorts first: multi-variant (a bias signal) → a non-control variant the session saw → control.
export function experimentSignalRank(item: ExperimentSessionContextItemApi): number {
    if (item.multiple_variants) {
        return 0
    }
    return isControlVariant(item) ? 2 : 1
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
        experimentContextEnabled: [
            (s) => [s.featureFlags, (_, props) => props.sessionRecordingId],
            (featureFlags, sessionRecordingId): boolean =>
                !!featureFlags[FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT] && !!sessionRecordingId,
        ],
        experimentItems: [
            (s) => [s.experimentContext],
            (experimentContext): ExperimentSessionContextItemApi[] => experimentContext?.results ?? [],
        ],
        // Experiments with an exposure event during this recording — these have a moment on the timeline to jump to.
        seenItems: [
            (s) => [s.experimentItems],
            (experimentItems: ExperimentSessionContextItemApi[]): ExperimentSessionContextItemApi[] =>
                experimentItems
                    .filter((item) => item.first_exposure_timestamp != null)
                    .sort(
                        (a, b) =>
                            experimentSignalRank(a) - experimentSignalRank(b) ||
                            (a.first_exposure_timestamp ?? '').localeCompare(b.first_exposure_timestamp ?? '')
                    ),
        ],
        // Experiments the person is enrolled in but with no exposure event in this session — the variant
        // is only known from stamped flag properties.
        enrolledItems: [
            (s) => [s.experimentItems],
            (experimentItems: ExperimentSessionContextItemApi[]): ExperimentSessionContextItemApi[] =>
                experimentItems
                    .filter((item) => item.first_exposure_timestamp == null)
                    .sort(
                        (a, b) =>
                            experimentSignalRank(a) - experimentSignalRank(b) ||
                            a.experiment_name.localeCompare(b.experiment_name)
                    ),
        ],
        seenCount: [(s) => [s.seenItems], (seenItems: ExperimentSessionContextItemApi[]): number => seenItems.length],
        enrolledCount: [
            (s) => [s.enrolledItems],
            (enrolledItems: ExperimentSessionContextItemApi[]): number => enrolledItems.length,
        ],
        hasExperimentContext: [
            (s) => [s.experimentItems],
            (experimentItems: ExperimentSessionContextItemApi[]): boolean => experimentItems.length > 0,
        ],
        // Scoped to seenItems: this warns the chip that summarizes only in-recording experiments, so an
        // enrollment without an in-session exposure that saw multiple variants must not trigger the warning.
        hasMultipleVariantWarning: [
            (s) => [s.seenItems],
            (seenItems: ExperimentSessionContextItemApi[]): boolean => seenItems.some((item) => item.multiple_variants),
        ],
    }),
    // Feature flags can arrive after the player mounts (posthog-js loads them asynchronously),
    // so re-attempt the load when the gate flips on rather than only once at mount.
    subscriptions(({ actions, values }) => ({
        experimentContextEnabled: (enabled: boolean) => {
            if (enabled && !values.experimentContext && !values.experimentContextLoading) {
                actions.loadExperimentContext()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.experimentContextLoading) {
            actions.loadExperimentContext()
        }
    }),
])
