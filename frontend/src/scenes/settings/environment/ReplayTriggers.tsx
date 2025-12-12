import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonLabel,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    LemonSnack,
    LemonTab,
    LemonTabs,
    LemonTag,
    Link,
    Popover,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TriggerMatchChoice } from 'lib/components/Triggers/TriggerMatchChoice'
import { TriggersSummary } from 'lib/components/Triggers/TriggersSummary'
import { UrlConfig } from 'lib/components/Triggers/UrlConfig'
import { FeatureFlagTrigger, Trigger, TriggerType } from 'lib/components/Triggers/types'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { isNumeric } from 'lib/utils'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'
import {
    ReplayPlatform,
    isStringWithLength,
    replayTriggersLogic,
} from 'scenes/settings/environment/replayTriggersLogic'
import { sessionReplayIngestionControlLogic } from 'scenes/settings/environment/sessionReplayIngestionControlLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlLevel,
    AccessControlResourceType,
    AvailableFeature,
    MultivariateFlagOptions,
    TeamPublicType,
    TeamType,
} from '~/types'

export const ANY_VARIANT = 'any'

export function variantOptions(
    multivariate: MultivariateFlagOptions | undefined,
    disabledReason?: string | null
): LemonSegmentedButtonOption<string>[] {
    if (!multivariate) {
        return []
    }
    return [
        {
            label: ANY_VARIANT,
            value: ANY_VARIANT,
            disabledReason: disabledReason ?? undefined,
        },
        ...multivariate.variants.map((variant) => {
            return {
                label: variant.key,
                value: variant.key,
                disabledReason: disabledReason ?? undefined,
            }
        }),
    ]
}

function LinkedFlagSelector(): JSX.Element | null {
    const { selectedPlatform } = useValues(replayTriggersLogic)

    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)

    const { hasAvailableFeature } = useValues(userLogic)

    const featureFlagRecordingFeatureEnabled = hasAvailableFeature(AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING)

    const { linkedFlag, featureFlagLoading, flagHasVariants } = useValues(sessionReplayIngestionControlLogic)
    const { selectFeatureFlag } = useActions(sessionReplayIngestionControlLogic)

    if (!featureFlagRecordingFeatureEnabled) {
        return null
    }

    return (
        <>
            <div className="flex flex-col deprecated-space-y-2 mt-2">
                <div className="flex justify-between">
                    <LemonLabel className="text-base">
                        {selectedPlatform === 'mobile' ? null : <TriggerMatchTypeTag />} Enable recordings using feature
                        flag {featureFlagLoading && <Spinner />}{' '}
                        <Since
                            web={{ version: '1.110.0' }}
                            ios={{ version: '3.11.0' }}
                            android={{ version: '3.11.0' }}
                            reactNative={{ version: '3.6.3' }}
                            flutter={{ version: '4.7.0' }}
                        />
                    </LemonLabel>
                    <div className="flex flex-row justify-start">
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <FlagSelector
                                    value={currentTeam?.session_recording_linked_flag?.id ?? undefined}
                                    onChange={(id, key, flag) => {
                                        selectFeatureFlag(flag)
                                        updateCurrentTeam({ session_recording_linked_flag: { id, key, variant: null } })
                                    }}
                                    disabledReason={
                                        (disabledReason ?? (currentTeamLoading || featureFlagLoading))
                                            ? 'Loading...'
                                            : undefined
                                    }
                                    readOnly={!!disabledReason || currentTeamLoading || featureFlagLoading}
                                />
                            )}
                        </AccessControlAction>
                        {currentTeam?.session_recording_linked_flag && (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.SessionRecording}
                                minAccessLevel={AccessControlLevel.Editor}
                            >
                                <LemonButton
                                    className="ml-2"
                                    icon={<IconCancel />}
                                    size="small"
                                    type="secondary"
                                    onClick={() => updateCurrentTeam({ session_recording_linked_flag: null })}
                                    title="Clear selected flag"
                                    loading={currentTeamLoading || featureFlagLoading}
                                />
                            </AccessControlAction>
                        )}
                    </div>
                </div>

                <p>
                    Only record when this flag is enabled. <strong>Shared across web and mobile.</strong>
                </p>
                {flagHasVariants && (
                    <>
                        <LemonLabel className="text-base">
                            Link to a specific flag variant{' '}
                            <Tooltip
                                delayMs={200}
                                title={
                                    <>
                                        <p>Record for "any" variant, or only for a specific variant.</p>
                                        <p>Variant targeting requires posthog-js v1.110.0+</p>
                                    </>
                                }
                            >
                                <IconInfo className="text-muted-alt cursor-help" />
                            </Tooltip>
                        </LemonLabel>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <LemonSegmentedButton
                                    className="min-w-1/3"
                                    value={currentTeam?.session_recording_linked_flag?.variant ?? ANY_VARIANT}
                                    options={variantOptions(
                                        linkedFlag?.filters.multivariate,
                                        (disabledReason ?? (currentTeamLoading || featureFlagLoading))
                                            ? 'Loading...'
                                            : undefined
                                    )}
                                    onChange={(variant) => {
                                        if (!linkedFlag) {
                                            return
                                        }

                                        updateCurrentTeam({
                                            session_recording_linked_flag: {
                                                id: linkedFlag?.id,
                                                key: linkedFlag?.key,
                                                variant: variant === ANY_VARIANT ? null : variant,
                                            },
                                        })
                                    }}
                                />
                            )}
                        </AccessControlAction>
                    </>
                )}
            </div>
        </>
    )
}

function UrlTriggerOptions(): JSX.Element | null {
    const {
        isAddUrlTriggerConfigFormVisible,
        urlTriggerConfig,
        editUrlTriggerIndex,
        isProposedUrlTriggerSubmitting,
        checkUrlTrigger,
        checkUrlTriggerResults,
        urlTriggerInputValidationWarning,
    } = useValues(replayTriggersLogic)
    const {
        addUrlTrigger,
        newUrlTrigger,
        removeUrlTrigger,
        setEditUrlTriggerIndex,
        cancelProposingUrlTrigger,
        setCheckUrlTrigger,
    } = useActions(replayTriggersLogic)

    return (
        <UrlConfig
            logic={replayTriggersLogic}
            formKey="proposedUrlTrigger"
            addUrl={addUrlTrigger}
            validationWarning={urlTriggerInputValidationWarning}
            title="Enable recordings when URL matches"
            description="Adding a URL trigger means recording will only be started when the user visits a page that matches the URL."
            checkUrl={checkUrlTrigger}
            checkUrlResults={checkUrlTriggerResults}
            setCheckUrl={setCheckUrlTrigger}
            isAddFormVisible={isAddUrlTriggerConfigFormVisible}
            config={urlTriggerConfig}
            editIndex={editUrlTriggerIndex}
            isSubmitting={isProposedUrlTriggerSubmitting}
            onAdd={newUrlTrigger}
            onCancel={cancelProposingUrlTrigger}
            onEdit={setEditUrlTriggerIndex}
            onRemove={removeUrlTrigger}
        />
    )
}

function UrlBlocklistOptions(): JSX.Element | null {
    const {
        isAddUrlBlocklistConfigFormVisible,
        urlBlocklistConfig,
        editUrlBlocklistIndex,
        isProposedUrlBlocklistSubmitting,
        checkUrlBlocklist,
        checkUrlBlocklistResults,
        urlBlocklistInputValidationWarning,
    } = useValues(replayTriggersLogic)
    const {
        addUrlBlocklist,
        newUrlBlocklist,
        removeUrlBlocklist,
        setEditUrlBlocklistIndex,
        cancelProposingUrlBlocklist,
        setCheckUrlBlocklist,
    } = useActions(replayTriggersLogic)

    return (
        <UrlConfig
            logic={replayTriggersLogic}
            formKey="proposedUrlBlocklist"
            addUrl={addUrlBlocklist}
            validationWarning={urlBlocklistInputValidationWarning}
            title="Pause recordings when the user visits a page that matches the URL"
            description="Used to pause recordings for part of a user journey"
            checkUrl={checkUrlBlocklist}
            checkUrlResults={checkUrlBlocklistResults}
            setCheckUrl={setCheckUrlBlocklist}
            isAddFormVisible={isAddUrlBlocklistConfigFormVisible}
            config={urlBlocklistConfig}
            editIndex={editUrlBlocklistIndex}
            isSubmitting={isProposedUrlBlocklistSubmitting}
            onAdd={newUrlBlocklist}
            onCancel={cancelProposingUrlBlocklist}
            onEdit={setEditUrlBlocklistIndex}
            onRemove={removeUrlBlocklist}
        />
    )
}

function EventSelectButton(): JSX.Element {
    const { eventTriggerConfig } = useValues(replayTriggersLogic)
    const { updateEventTriggerConfig } = useActions(replayTriggersLogic)

    const [open, setOpen] = useState<boolean>(false)
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.SessionRecording}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            if (isStringWithLength(value)) {
                                updateEventTriggerConfig(Array.from(new Set(eventTriggerConfig?.concat([value]))))
                            }
                            setOpen(false)
                        }}
                        excludedProperties={{
                            [TaxonomicFilterGroupType.Events]: [null], // This will hide "All events"
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    />
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    sideIcon={null}
                    onClick={() => setOpen(!open)}
                >
                    Add event
                </LemonButton>
            </Popover>
        </AccessControlAction>
    )
}

function EventTriggerOptions(): JSX.Element | null {
    const { eventTriggerConfig } = useValues(replayTriggersLogic)
    const { updateEventTriggerConfig } = useActions(replayTriggersLogic)

    return (
        <div className="flex flex-col deprecated-space-y-2 mt-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    <TriggerMatchTypeTag /> Event emitted <Since web={{ version: '1.186.0' }} />
                </LemonLabel>
                <EventSelectButton />
            </div>
            <p>Start recording when a PostHog event is queued.</p>

            <div className="flex gap-2 flex-wrap">
                {eventTriggerConfig?.map((trigger) => (
                    <AccessControlAction
                        key={trigger}
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        {({ disabledReason }) => (
                            <LemonSnack
                                onClose={
                                    !disabledReason
                                        ? () => {
                                              updateEventTriggerConfig(eventTriggerConfig?.filter((e) => e !== trigger))
                                          }
                                        : undefined
                                }
                            >
                                {trigger}
                            </LemonSnack>
                        )}
                    </AccessControlAction>
                ))}
            </div>
        </div>
    )
}

function Sampling(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <div className="flex flex-row justify-between mt-2">
                <LemonLabel className="text-base">
                    <TriggerMatchTypeTag /> Sampling <Since web={{ version: '1.85.0' }} />
                </LemonLabel>
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
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
                </AccessControlAction>
            </div>
            <p>Choose how many sessions to record. 100% = record every session, 50% = record roughly half.</p>
        </>
    )
}

function MinimumDurationSetting(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}>
            <>
                <div className="flex flex-row justify-between">
                    <LemonLabel className="text-base">
                        Minimum session duration (seconds) <Since web={{ version: '1.85.0' }} />
                    </LemonLabel>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.SessionRecording}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonSelect
                            dropdownMatchSelectWidth={false}
                            onChange={(v) => {
                                updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })
                            }}
                            options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS}
                            value={currentTeam?.session_recording_minimum_duration_milliseconds}
                        />
                    </AccessControlAction>
                </div>
                <Tooltip
                    delayMs={200}
                    title={
                        <>
                            The JS SDK has an in-memory queue. This means that for traditional web apps the minimum
                            duration control is best effort.{' '}
                            <Link to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations">
                                Read more in our docs
                            </Link>
                        </>
                    }
                >
                    Setting a minimum session duration will ensure that only sessions that last longer than that value
                    are collected. This helps you avoid collecting sessions that are too short to be useful.
                </Tooltip>
            </>
        </PayGateMini>
    )
}

function TriggerMatchTypeTag(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    // Let's follow PostHog style of AND / OR from funnels
    return (
        <LemonTag type="danger" className="my-2 mr-2">
            {currentTeam?.session_recording_trigger_match_type_config &&
            currentTeam?.session_recording_trigger_match_type_config === 'any'
                ? 'OR'
                : 'AND'}
        </LemonTag>
    )
}

export function ReplayTriggers(): JSX.Element {
    const { selectedPlatform } = useValues(replayTriggersLogic)
    const { selectPlatform } = useActions(replayTriggersLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const tabs: LemonTab<'web' | 'mobile'>[] = [
        {
            key: 'web',
            label: 'Web',
            content: (
                <div className="flex flex-col gap-y-2">
                    {currentTeam && (
                        <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />
                    )}
                    <div className="border rounded py-2 px-4 mb-2 gap-y-2">
                        <TriggerMatchChoice
                            value={currentTeam?.session_recording_trigger_match_type_config || 'all'}
                            onChange={(value) =>
                                updateCurrentTeam({ session_recording_trigger_match_type_config: value })
                            }
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        />
                        <LemonDivider />
                        <UrlTriggerOptions />
                        <EventTriggerOptions />
                        <PayGateMini feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}>
                            <LinkedFlagSelector />
                        </PayGateMini>
                        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING}>
                            <Sampling />
                        </PayGateMini>
                    </div>
                    <MinimumDurationSetting />
                    <LemonDivider />
                    <UrlBlocklistOptions />
                </div>
            ),
        },
        {
            key: 'mobile',
            label: 'Mobile',
            content: (
                <div className="flex flex-col gap-y-2">
                    {currentTeam && (
                        <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />
                    )}
                    <PayGateMini feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}>
                        <LinkedFlagSelector />
                    </PayGateMini>
                </div>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-y-2">
            <LemonTabs activeKey={selectedPlatform} onChange={selectPlatform} tabs={tabs} />
        </div>
    )
}

const RecordingTriggersSummary = ({
    currentTeam,
    selectedPlatform,
}: {
    currentTeam: TeamType | TeamPublicType
    selectedPlatform: ReplayPlatform
}): JSX.Element => {
    const triggers = useTriggers(currentTeam, selectedPlatform)

    if (!currentTeam?.session_recording_opt_in) {
        return (
            <LemonBanner type="warning">
                <strong>Recording is disabled.</strong> Enable it in General settings.
            </LemonBanner>
        )
    }

    return <TriggersSummary triggers={triggers} />
}

const useTriggers = (currentTeam: TeamType | TeamPublicType, selectedPlatform: 'web' | 'mobile'): Trigger[] => {
    const { urlTriggerConfig, eventTriggerConfig } = useValues(replayTriggersLogic)

    const hasUrlTriggers = (urlTriggerConfig?.length ?? 0) > 0
    const hasEventTriggers = (eventTriggerConfig?.length ?? 0) > 0
    const hasFeatureFlag = !!currentTeam.session_recording_linked_flag
    const sampleRate = currentTeam.session_recording_sample_rate
    const numericSampleRate = sampleRate ? Math.floor(parseFloat(sampleRate) * 100) : null
    const hasSampling = isNumeric(numericSampleRate) && numericSampleRate < 100
    const hasMinDuration = !!currentTeam.session_recording_minimum_duration_milliseconds
    const hasUrlBlocklist = (currentTeam.session_recording_url_blocklist_config?.length ?? 0) > 0

    const isWebPlatform = selectedPlatform === 'web'

    const flagTrigger: FeatureFlagTrigger = {
        type: TriggerType.FEATURE_FLAG,
        enabled: hasFeatureFlag,
        key: currentTeam.session_recording_linked_flag?.key ?? null,
    }

    if (isWebPlatform) {
        return [
            {
                type: TriggerType.URL_MATCH,
                enabled: hasUrlTriggers,
                urls: urlTriggerConfig,
            },
            {
                type: TriggerType.EVENT,
                enabled: hasEventTriggers,
                events: eventTriggerConfig,
            },
            flagTrigger,
            {
                type: TriggerType.SAMPLING,
                enabled: hasSampling,
                sampleRate: numericSampleRate,
            },
            {
                type: TriggerType.MIN_DURATION,
                enabled: hasMinDuration,
                minDurationMs: hasMinDuration
                    ? (currentTeam.session_recording_minimum_duration_milliseconds ?? 0)
                    : null,
            },
            {
                type: TriggerType.URL_BLOCKLIST,
                enabled: hasUrlBlocklist,
                urls: currentTeam.session_recording_url_blocklist_config ?? null,
            },
        ]
    }

    return [flagTrigger]
}
