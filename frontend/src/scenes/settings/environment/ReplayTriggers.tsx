import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCollapse, LemonLabel, LemonTab, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'
import { TriggerGroupsEditor } from 'lib/components/IngestionControls/triggers/triggerGroups/TriggerGroupsEditor'
import { FeatureFlagTrigger, Trigger, TriggerType } from 'lib/components/IngestionControls/types'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'
import { ReplayPlatform, replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlResourceType, AvailableFeature, TeamPublicType, TeamType } from '~/types'

export const TRIGGER_GROUPS_MIN_SDK_VERSION = '1.369.0'

/** Convert the stored sample-rate string (decimal 0–1) to a display percentage (0–100). */
function toDisplaySampleRate(rate: string | null | undefined): number {
    return typeof rate === 'string' ? Math.floor(parseFloat(rate) * 100) : 100
}

function TriggerPanelHeader({
    title,
    status,
    showMatchTag = false,
}: {
    title: string
    status: string
    showMatchTag?: boolean
}): JSX.Element {
    return (
        <div className="flex items-center justify-between w-full">
            <span className="font-semibold flex items-center gap-1">
                {showMatchTag && <IngestionControls.MatchTypeTag />}
                {title}
            </span>
            <span className="text-muted text-xs font-normal">{status}</span>
        </div>
    )
}

function LinkedFlagSelector(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}>
            <IngestionControls.FlagTrigger
                logicKey="session-replay-linked-flag"
                flag={currentTeam?.session_recording_linked_flag ?? null}
                onChange={(v) => updateCurrentTeam({ session_recording_linked_flag: v })}
            >
                <div className="flex flex-col gap-2">
                    <div className="flex justify-between items-center">
                        <LemonLabel className="text-base">
                            Select feature flag{' '}
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
            logicProps={{}}
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
            logicProps={{}}
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
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    Select events <Since web={{ version: '1.186.0' }} />
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
            <div className="flex flex-col gap-2">
                <div className="flex flex-row justify-between items-center">
                    <LemonLabel className="text-base">
                        Sample rate{' '}
                        <Since
                            web={{ version: '1.85.0' }}
                            android={{ version: '3.34.0' }}
                            ios={{ version: '3.42.0' }}
                            reactNative={{ version: '4.37.0' }}
                        />
                    </LemonLabel>
                    <IngestionControls.SamplingTrigger
                        initialSampleRate={toDisplaySampleRate(currentTeam?.session_recording_sample_rate)}
                        onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                    />
                </div>
                <p>Choose how many sessions to record. 100% = record every session, 50% = record roughly half.</p>
            </div>
        </PayGateMini>
    )
}

function MobileSampling(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const sampleRate = toDisplaySampleRate(currentTeam?.session_recording_sample_rate)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row items-center gap-2">
                <LemonLabel className="text-base">
                    Sample rate{' '}
                    <Since
                        android={{ version: '3.34.0' }}
                        ios={{ version: '3.42.0' }}
                        reactNative={{ version: '4.37.0' }}
                    />
                </LemonLabel>
                <Tooltip title="Sample rate is shared across web and mobile. Change it on the Web tab.">
                    <span className="text-muted font-semibold">{sampleRate}%</span>
                </Tooltip>
            </div>
            <p className="text-muted-alt">
                Sample rate is shared across all platforms.{' '}
                <span className="font-semibold">Change this setting on the Web tab.</span>
            </p>
        </div>
    )
}

function MinimumDurationSetting(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <PayGateMini feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}>
            <div className="flex flex-col gap-2">
                <div className="flex flex-row justify-between items-center">
                    <LemonLabel className="text-base">
                        Duration threshold <Since web={{ version: '1.85.0' }} />
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
            </div>
        </PayGateMini>
    )
}

function useHeaderStatuses(currentTeam: TeamType | TeamPublicType | null): {
    urlStatus: string
    eventStatus: string
    flagStatus: string
    samplingStatus: string
    minDurationStatus: string
    blocklistStatus: string
} {
    const { urlTriggerConfig, eventTriggerConfig } = useValues(replayTriggersLogic)

    const urlCount = urlTriggerConfig?.length ?? 0
    const eventCount = eventTriggerConfig?.length ?? 0
    const flagKey = currentTeam?.session_recording_linked_flag?.key
    const numericSampleRate = toDisplaySampleRate(currentTeam?.session_recording_sample_rate)
    const minDurationMs = currentTeam?.session_recording_minimum_duration_milliseconds
    const blocklistCount = currentTeam?.session_recording_url_blocklist_config?.length ?? 0

    return {
        urlStatus: urlCount > 0 ? pluralize(urlCount, 'pattern') : 'Not configured',
        eventStatus: eventCount > 0 ? pluralize(eventCount, 'event') : 'Not configured',
        flagStatus: flagKey ? flagKey : 'Not configured',
        samplingStatus: `${numericSampleRate}%${numericSampleRate === 100 ? ' (default)' : ''}`,
        minDurationStatus: minDurationMs ? `${minDurationMs / 1000}s` : 'No minimum',
        blocklistStatus: blocklistCount > 0 ? pluralize(blocklistCount, 'pattern') : 'Not configured',
    }
}

export function ReplayTriggers(): JSX.Element {
    const { selectedPlatform } = useValues(replayTriggersLogic)
    const { selectPlatform } = useActions(replayTriggersLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const statuses = useHeaderStatuses(currentTeam)

    const isV2TriggersEnabled = featureFlags[FEATURE_FLAGS.REPLAY_TRIGGERS_V2]

    const tabs: LemonTab<'web' | 'mobile'>[] = [
        {
            key: 'web',
            label: 'Web',
            content: (
                <div className="flex flex-col gap-y-4">
                    {isV2TriggersEnabled && (
                        <>
                            <LemonBanner type="warning">
                                <strong>JavaScript SDK version compatibility</strong>
                                <ul className="list-disc ml-4 mt-2 space-y-1">
                                    <li>
                                        Older SDK versions (&lt; v{TRIGGER_GROUPS_MIN_SDK_VERSION}) will use the legacy
                                        recording conditions below
                                    </li>
                                    <li>
                                        Newer SDK versions (&gt;= v{TRIGGER_GROUPS_MIN_SDK_VERSION}) will use trigger
                                        groups if configured, otherwise will fallback to the legacy recording conditions
                                    </li>
                                    <li>
                                        Both configurations are sent to ensure backward compatibility with all
                                        JavaScript SDK versions
                                    </li>
                                </ul>
                            </LemonBanner>

                            <TriggerGroupsEditor />

                            <h3 className="text-base font-semibold">Legacy recording conditions</h3>
                            <LemonBanner type="warning">
                                Used by SDK versions &lt; v{TRIGGER_GROUPS_MIN_SDK_VERSION} and as fallback for newer
                                versions if trigger groups are not configured.
                            </LemonBanner>
                        </>
                    )}

                    {currentTeam && (
                        <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />
                    )}

                    <IngestionControls.MatchTypeSelect />

                    <div>
                        <h3 className="text-sm font-semibold mb-2">Recording conditions</h3>
                        <LemonCollapse
                            multiple
                            panels={[
                                {
                                    key: 'url',
                                    header: (
                                        <TriggerPanelHeader
                                            title="URL matches"
                                            status={statuses.urlStatus}
                                            showMatchTag
                                        />
                                    ),
                                    content: <UrlTriggerOptions />,
                                },
                                {
                                    key: 'event',
                                    header: (
                                        <TriggerPanelHeader
                                            title="Event emitted"
                                            status={statuses.eventStatus}
                                            showMatchTag
                                        />
                                    ),
                                    content: <EventTriggerOptions />,
                                },
                                {
                                    key: 'flag',
                                    header: (
                                        <TriggerPanelHeader
                                            title="Feature flag"
                                            status={statuses.flagStatus}
                                            showMatchTag
                                        />
                                    ),
                                    content: <LinkedFlagSelector />,
                                },
                            ]}
                        />
                    </div>

                    <div>
                        <h3 className="text-sm font-semibold mb-2">Recording limits</h3>
                        <LemonCollapse
                            multiple
                            panels={[
                                {
                                    key: 'sampling',
                                    header: (
                                        <TriggerPanelHeader
                                            title="Sampling"
                                            status={statuses.samplingStatus}
                                            showMatchTag
                                        />
                                    ),
                                    content: <Sampling />,
                                },
                                {
                                    key: 'min-duration',
                                    header: (
                                        <TriggerPanelHeader
                                            title="Minimum duration"
                                            status={statuses.minDurationStatus}
                                        />
                                    ),
                                    content: <MinimumDurationSetting />,
                                },
                            ]}
                        />
                    </div>

                    <div>
                        <h3 className="text-base font-semibold mb-2">
                            Recording exclusions <Since web={{ version: '1.171.0' }} />
                        </h3>
                        <LemonCollapse
                            multiple
                            panels={[
                                {
                                    key: 'blocklist',
                                    header: (
                                        <TriggerPanelHeader title="URL blocklist" status={statuses.blocklistStatus} />
                                    ),
                                    content: <UrlBlocklistOptions />,
                                },
                            ]}
                        />
                    </div>
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
                    <MobileSampling />
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

    return (
        <IngestionControlsSummary
            triggers={triggers}
            controlDescription="sessions recorded"
            docsLink={{
                to: 'https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record',
                label: 'Read about how to start and stop sessions in our docs.',
            }}
        />
    )
}

const useTriggers = (currentTeam: TeamType | TeamPublicType, selectedPlatform: 'web' | 'mobile'): Trigger[] => {
    const { urlTriggerConfig, eventTriggerConfig } = useValues(replayTriggersLogic)

    const hasUrlTriggers = (urlTriggerConfig?.length ?? 0) > 0
    const hasEventTriggers = (eventTriggerConfig?.length ?? 0) > 0
    const hasFeatureFlag = !!currentTeam.session_recording_linked_flag
    const sampleRate = currentTeam.session_recording_sample_rate
    const hasSampling = toDisplaySampleRate(sampleRate) < 100
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
                sampleRate: sampleRate ? parseFloat(sampleRate) : null,
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

    return [
        flagTrigger,
        {
            type: TriggerType.SAMPLING,
            enabled: hasSampling,
            sampleRate: sampleRate ? parseFloat(sampleRate) : null,
        },
    ]
}
