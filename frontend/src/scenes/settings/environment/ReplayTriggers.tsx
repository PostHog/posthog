import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDivider, LemonLabel, LemonTab, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'
import { FeatureFlagTrigger, Trigger, TriggerType } from 'lib/components/IngestionControls/types'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { isNumeric } from 'lib/utils'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'
import { ReplayPlatform, replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlResourceType, AvailableFeature, TeamPublicType, TeamType } from '~/types'

function LinkedFlagSelector(): JSX.Element | null {
    const { selectedPlatform } = useValues(replayTriggersLogic)

    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}>
            <IngestionControls.FlagTrigger
                logicKey="session-replay-linked-flag"
                flag={currentTeam?.session_recording_linked_flag ?? null}
                onChange={(v) => updateCurrentTeam({ session_recording_linked_flag: v })}
            >
                <div className="flex flex-col deprecated-space-y-2 mt-2">
                    <div className="flex justify-between">
                        <LemonLabel className="text-base">
                            {selectedPlatform === 'mobile' ? null : <IngestionControls.MatchTypeTag />} Enable
                            recordings using feature flag
                            <Since
                                web={{ version: '1.110.0' }}
                                ios={{ version: '3.11.0' }}
                                android={{ version: '3.11.0' }}
                                reactNative={{ version: '3.6.3' }}
                                flutter={{ version: '4.7.0' }}
                            />
                        </LemonLabel>
                        <IngestionControls.FlagSelector />
                    </div>

                    <p>
                        Only record when this flag is enabled. <strong>Shared across web and mobile.</strong>
                    </p>
                    <IngestionControls.FlagVariantSelector
                        tooltip={
                            <>
                                <p>Record for "any" variant, or only for a specific variant.</p>
                                <p>Variant targeting requires posthog-js v1.110.0+</p>
                            </>
                        }
                    />
                </div>
            </IngestionControls.FlagTrigger>
        </PayGateMini>
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
        <IngestionControls.UrlConfig
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
        <IngestionControls.UrlConfig
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

function EventTriggerOptions(): JSX.Element | null {
    const { eventTriggerConfig } = useValues(replayTriggersLogic)
    const { updateEventTriggerConfig } = useActions(replayTriggersLogic)

    return (
        <div className="flex flex-col deprecated-space-y-2 mt-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    <IngestionControls.MatchTypeTag /> Event emitted <Since web={{ version: '1.186.0' }} />
                </LemonLabel>
                <IngestionControls.EventTriggerSelect events={eventTriggerConfig} onChange={updateEventTriggerConfig} />
            </div>
            <p>Start recording when a PostHog event is queued.</p>

            <div className="flex gap-2 flex-wrap">
                {eventTriggerConfig?.map((trigger) => (
                    <IngestionControls.EventTrigger
                        key={trigger}
                        trigger={trigger}
                        onClose={() => updateEventTriggerConfig(eventTriggerConfig?.filter((e) => e !== trigger))}
                    />
                ))}
            </div>
        </div>
    )
}

function Sampling(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING}>
            <div className="flex flex-row justify-between mt-2">
                <LemonLabel className="text-base">
                    <IngestionControls.MatchTypeTag /> Sampling <Since web={{ version: '1.85.0' }} />
                </LemonLabel>
                <IngestionControls.SamplingTrigger
                    initialSampleRate={
                        typeof currentTeam?.session_recording_sample_rate === 'string'
                            ? Math.floor(parseFloat(currentTeam?.session_recording_sample_rate) * 100)
                            : 100
                    }
                    onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                />
            </div>
            <p>Choose how many sessions to record. 100% = record every session, 50% = record roughly half.</p>
        </PayGateMini>
    )
}

function MinimumDurationSetting(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}>
            <div className="flex flex-row justify-between">
                <LemonLabel className="text-base">
                    Minimum session duration (seconds) <Since web={{ version: '1.85.0' }} />
                </LemonLabel>
                <IngestionControls.MinDuration
                    value={currentTeam?.session_recording_minimum_duration_milliseconds}
                    onChange={(v) => updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })}
                />
            </div>
            <Tooltip
                delayMs={200}
                title={
                    <>
                        The JS SDK has an in-memory queue. This means that for traditional web apps the minimum duration
                        control is best effort.{' '}
                        <Link to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations">
                            Read more in our docs
                        </Link>
                    </>
                }
            >
                Setting a minimum session duration will ensure that only sessions that last longer than that value are
                collected. This helps you avoid collecting sessions that are too short to be useful.
            </Tooltip>
        </PayGateMini>
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
                    <div className="flex flex-col gap-y-2 border rounded py-2 px-4 mb-2">
                        <IngestionControls.MatchTypeSelect />
                        <LemonDivider />
                        <UrlTriggerOptions />
                        <EventTriggerOptions />
                        <LinkedFlagSelector />
                        <Sampling />
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
                    <LinkedFlagSelector />
                </div>
            ),
        },
    ]

    return (
        <IngestionControls
            logicKey="session-replay"
            resourceType={AccessControlResourceType.SessionRecording}
            matchType={currentTeam?.session_recording_trigger_match_type_config || 'all'}
            onChangeMatchType={(value) => updateCurrentTeam({ session_recording_trigger_match_type_config: value })}
        >
            <div className="flex flex-col gap-y-2">
                <LemonTabs activeKey={selectedPlatform} onChange={selectPlatform} tabs={tabs} />
            </div>
        </IngestionControls>
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

    return <IngestionControlsSummary triggers={triggers} />
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
