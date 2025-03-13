import {
    LemonButton,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    Link,
    Spinner,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { SupportedPlatforms } from 'scenes/settings/environment/SessionRecordingSettings'
import { sessionReplayIngestionControlLogic } from 'scenes/settings/environment/sessionReplayIngestionControlLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, MultivariateFlagOptions } from '~/types'

function variantOptions(multivariate: MultivariateFlagOptions | undefined): LemonSegmentedButtonOption<string>[] {
    if (!multivariate) {
        return []
    }
    return [
        {
            label: 'any',
            value: 'any',
        },
        ...multivariate.variants.map((variant) => {
            return {
                label: variant.key,
                value: variant.key,
            }
        }),
    ]
}

function LinkedFlagSelector(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const { hasAvailableFeature } = useValues(userLogic)

    const featureFlagRecordingFeatureEnabled = hasAvailableFeature(AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING)

    const { linkedFlag, featureFlagLoading, flagHasVariants } = useValues(sessionReplayIngestionControlLogic)
    const { selectFeatureFlag } = useActions(sessionReplayIngestionControlLogic)

    if (!featureFlagRecordingFeatureEnabled) {
        return null
    }

    return (
        <>
            <div className="flex flex-col deprecated-space-y-2">
                <LemonLabel className="text-base">
                    Enable recordings using feature flag {featureFlagLoading && <Spinner />}
                </LemonLabel>
                <SupportedPlatforms
                    web={{ version: '1.110.0' }}
                    ios={{ version: '3.11.0' }}
                    android={{ version: '3.11.0' }}
                    reactNative={{ version: '3.6.3' }}
                    flutter={{ version: '4.7.0' }}
                />
                <p>Linking a flag means that recordings will only be collected for users who have the flag enabled.</p>
                <div className="flex flex-row justify-start">
                    <FlagSelector
                        value={currentTeam?.session_recording_linked_flag?.id ?? undefined}
                        onChange={(id, key, flag) => {
                            selectFeatureFlag(flag)
                            updateCurrentTeam({ session_recording_linked_flag: { id, key, variant: null } })
                        }}
                    />
                    {currentTeam?.session_recording_linked_flag && (
                        <LemonButton
                            className="ml-2"
                            icon={<IconCancel />}
                            size="small"
                            type="secondary"
                            onClick={() => updateCurrentTeam({ session_recording_linked_flag: null })}
                            title="Clear selected flag"
                        />
                    )}
                </div>
                {flagHasVariants && (
                    <>
                        <LemonLabel className="text-base">Link to a specific flag variant</LemonLabel>
                        <LemonSegmentedButton
                            className="min-w-1/3"
                            value={currentTeam?.session_recording_linked_flag?.variant ?? 'any'}
                            options={variantOptions(linkedFlag?.filters.multivariate)}
                            onChange={(variant) => {
                                if (!linkedFlag) {
                                    return
                                }

                                updateCurrentTeam({
                                    session_recording_linked_flag: {
                                        id: linkedFlag?.id,
                                        key: linkedFlag?.key,
                                        variant: variant === 'any' ? null : variant,
                                    },
                                })
                            }}
                        />
                        <p>
                            This is a multi-variant flag. You can link to "any" variant of the flag, and recordings will
                            start whenever the flag is enabled for a user.
                        </p>
                        <p>
                            Alternatively, you can link to a specific variant of the flag, and recordings will only
                            start when the user has that specific variant enabled. Variant targeting support requires
                            posthog-js v1.110.0 or greater
                        </p>
                    </>
                )}
            </div>
        </>
    )
}

export function SessionRecordingIngestionSettings(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const samplingControlFeatureEnabled = hasAvailableFeature(AvailableFeature.SESSION_REPLAY_SAMPLING)
    const recordingDurationMinimumFeatureEnabled = hasAvailableFeature(
        AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM
    )

    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING}>
            <>
                <p>
                    PostHog offers several tools to let you control the number of recordings you collect and which users
                    you collect recordings for.{' '}
                    <Link
                        to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record"
                        target="blank"
                    >
                        Learn more in our docs.
                    </Link>
                </p>

                {samplingControlFeatureEnabled && (
                    <>
                        <div className="flex flex-row justify-between">
                            <LemonLabel className="text-base">Sampling</LemonLabel>
                            <LemonSelect
                                onChange={(v) => {
                                    updateCurrentTeam({ session_recording_sample_rate: v })
                                }}
                                dropdownMatchSelectWidth={false}
                                options={[
                                    {
                                        label: '100% (no sampling)',
                                        value: '1.00',
                                    },
                                    {
                                        label: '95%',
                                        value: '0.95',
                                    },
                                    {
                                        label: '90%',
                                        value: '0.90',
                                    },
                                    {
                                        label: '85%',
                                        value: '0.85',
                                    },
                                    {
                                        label: '80%',
                                        value: '0.80',
                                    },
                                    {
                                        label: '75%',
                                        value: '0.75',
                                    },
                                    {
                                        label: '70%',
                                        value: '0.70',
                                    },
                                    {
                                        label: '65%',
                                        value: '0.65',
                                    },
                                    {
                                        label: '60%',
                                        value: '0.60',
                                    },
                                    {
                                        label: '55%',
                                        value: '0.55',
                                    },
                                    {
                                        label: '50%',
                                        value: '0.50',
                                    },
                                    {
                                        label: '45%',
                                        value: '0.45',
                                    },
                                    {
                                        label: '40%',
                                        value: '0.40',
                                    },
                                    {
                                        label: '35%',
                                        value: '0.35',
                                    },
                                    {
                                        label: '30%',
                                        value: '0.30',
                                    },
                                    {
                                        label: '25%',
                                        value: '0.25',
                                    },
                                    {
                                        label: '20%',
                                        value: '0.20',
                                    },
                                    {
                                        label: '15%',
                                        value: '0.15',
                                    },
                                    {
                                        label: '10%',
                                        value: '0.10',
                                    },
                                    {
                                        label: '5%',
                                        value: '0.05',
                                    },
                                    {
                                        label: '1%',
                                        value: '0.01',
                                    },
                                    {
                                        label: '0% (replay disabled)',
                                        value: '0.00',
                                    },
                                ]}
                                value={
                                    typeof currentTeam?.session_recording_sample_rate === 'string'
                                        ? currentTeam?.session_recording_sample_rate
                                        : '1.00'
                                }
                            />
                        </div>
                        <SupportedPlatforms web={{ version: '1.85.0' }} />
                        <p>
                            Use this setting to restrict the percentage of sessions that will be recorded. This is
                            useful if you want to reduce the amount of data you collect. 100% means all sessions will be
                            collected. 50% means roughly half of sessions will be collected.
                        </p>
                        <p>Sampling is only available for JavaScript Web.</p>
                    </>
                )}
                {recordingDurationMinimumFeatureEnabled && (
                    <>
                        <div className="flex flex-row justify-between">
                            <LemonLabel className="text-base">Minimum session duration (seconds)</LemonLabel>
                            <LemonSelect
                                dropdownMatchSelectWidth={false}
                                onChange={(v) => {
                                    updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })
                                }}
                                options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS}
                                value={currentTeam?.session_recording_minimum_duration_milliseconds}
                            />
                        </div>
                        <SupportedPlatforms web={{ version: '1.85.0' }} />
                        <p>
                            Setting a minimum session duration will ensure that only sessions that last longer than that
                            value are collected. This helps you avoid collecting sessions that are too short to be
                            useful.
                        </p>
                        <p>Minimum session duration is only available for JavaScript Web.</p>
                    </>
                )}
                <LinkedFlagSelector />
            </>
        </PayGateMini>
    )
}
