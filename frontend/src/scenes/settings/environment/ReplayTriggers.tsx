import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCollapse, LemonDivider, LemonLabel, LemonTab, LemonTabs, Tooltip } from '@posthog/lemon-ui'
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
    Button,
    Heading,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Separator,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    Tooltip as QuillTooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import IngestionControls from 'lib/components/IngestionControls'
import { IngestionControlsSummary } from 'lib/components/IngestionControls/Summary'
import { replayTriggersV2Logic } from 'lib/components/IngestionControls/triggers/triggerGroups/replayTriggersV2Logic'
import { TriggerGroupsEditor } from 'lib/components/IngestionControls/triggers/triggerGroups/TriggerGroupsEditor'
import { FeatureFlagTrigger, Trigger, TriggerType } from 'lib/components/IngestionControls/types'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import {
    ReplayPlatform,
    replayTriggersLogic,
    TRIGGER_GROUPS_MIN_SDK_VERSION,
} from 'scenes/settings/environment/replayTriggersLogic'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlResourceType, AvailableFeature, TeamPublicType, TeamType } from '~/types'

import { QuillSince } from './QuillSince'

export { TRIGGER_GROUPS_MIN_SDK_VERSION }

/** Convert the stored sample-rate string (decimal 0–1) to a display percentage (0–100). */
function toDisplaySampleRate(rate: string | null | undefined): number {
    return typeof rate === 'string' ? Math.floor(parseFloat(rate) * 100) : 100
}

function AnyWith100SamplingWarning({
    currentTeam,
    isV2TriggersEnabled,
}: {
    currentTeam: TeamType | TeamPublicType | null | undefined
    isV2TriggersEnabled: boolean
}): JSX.Element | null {
    const { urlTriggerConfig, eventTriggerConfig } = useValues(replayTriggersLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const matchType = currentTeam?.session_recording_trigger_match_type_config || 'all'
    const storedSampleRate = currentTeam?.session_recording_sample_rate
    const sampleRate = toDisplaySampleRate(storedSampleRate)
    const hasOtherCondition =
        (urlTriggerConfig?.length ?? 0) > 0 ||
        (eventTriggerConfig?.length ?? 0) > 0 ||
        !!currentTeam?.session_recording_linked_flag

    if (matchType !== 'any' || sampleRate !== 100 || storedSampleRate == null || !hasOtherCondition) {
        return null
    }

    if (todayRailNav) {
        return (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>
                        <strong>100% sampling rate with "any" matching records every session.</strong> To fix this,
                        either lower the sample rate or switch to "all" matching.
                        {isV2TriggersEnabled && (
                            <>
                                {' '}
                                Consider using <strong>trigger groups</strong> above for more precise control over when
                                sessions are recorded.
                            </>
                        )}
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="error">
            <strong>100% sampling rate with "any" matching records every session.</strong> To fix this, either lower the
            sample rate or switch to "all" matching.
            {isV2TriggersEnabled && (
                <>
                    {' '}
                    Consider using <strong>trigger groups</strong> above for more precise control over when sessions are
                    recorded.
                </>
            )}
        </LemonBanner>
    )
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="flex items-center gap-1 font-semibold">
                    {showMatchTag && <IngestionControls.MatchTypeTag />}
                    {title}
                </span>
                <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                    {status}
                </Text>
            </span>
        )
    }

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <PayGateMini
                feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}
                featureDetail="replay-feature-flag-trigger"
            >
                <IngestionControls.FlagTrigger
                    logicKey="session-replay-linked-flag"
                    flag={currentTeam?.session_recording_linked_flag ?? null}
                    onChange={(v) => updateCurrentTeam({ session_recording_linked_flag: v })}
                >
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                                Select feature flag
                                <QuillSince
                                    web={{ version: '1.110.0' }}
                                    ios={{ version: '3.11.0' }}
                                    android={{ version: '3.11.0' }}
                                    reactNative={{ version: '3.6.3' }}
                                    flutter={{ version: '4.7.0' }}
                                />
                            </Heading>
                            <IngestionControls.FlagSelector />
                        </div>
                        <Text size="xs" render={<p className="m-0" />}>
                            Only record when this flag is enabled. <strong>Shared across web and mobile.</strong>
                        </Text>
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

    return (
        <PayGateMini
            feature={AvailableFeature.REPLAY_FEATURE_FLAG_BASED_RECORDING}
            featureDetail="replay-feature-flag-trigger"
        >
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
            titleBadge={<Since web={{ version: '1.171.0' }} />}
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
            title="Pause recordings when URL matches"
            description="Pause recordings while the user is on a page that matches the URL."
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                        Select events <QuillSince web={{ version: '1.186.0' }} />
                    </Heading>
                    <IngestionControls.EventTriggerSelect
                        events={eventTriggerConfig}
                        onChange={updateEventTriggerConfig}
                    />
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    Start recording when a PostHog event is queued.
                </Text>
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const storedSampleRate = currentTeam?.session_recording_sample_rate

    if (todayRailNav) {
        return (
            <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING} featureDetail="session-replay-sampling">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                            Sample rate
                            <QuillSince
                                web={{ version: '1.85.0' }}
                                android={{ version: '3.34.0' }}
                                ios={{ version: '3.42.0' }}
                                reactNative={{ version: '4.37.0' }}
                            />
                            {storedSampleRate == null && (
                                <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                                    (default)
                                </Text>
                            )}
                        </Heading>
                        <IngestionControls.SamplingTrigger
                            initialSampleRate={toDisplaySampleRate(storedSampleRate)}
                            onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                        />
                    </div>
                    <Text size="xs" render={<p className="m-0" />}>
                        Choose how many sessions to record. 100% = record every session, 50% = record roughly half.
                    </Text>
                </div>
            </PayGateMini>
        )
    }

    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING} featureDetail="session-replay-sampling">
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
                        {storedSampleRate == null && <span className="text-muted font-normal"> (default)</span>}
                    </LemonLabel>
                    <IngestionControls.SamplingTrigger
                        initialSampleRate={toDisplaySampleRate(storedSampleRate)}
                        onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                    />
                </div>
                <p>Choose how many sessions to record. 100% = record every session, 50% = record roughly half.</p>
            </div>
        </PayGateMini>
    )
}

function MobileSampling(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const storedSampleRate = currentTeam?.session_recording_sample_rate

    if (todayRailNav) {
        return (
            <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING} featureDetail="session-replay-sampling">
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                            Sample rate
                            <QuillSince
                                android={{ version: '3.34.0' }}
                                ios={{ version: '3.42.0' }}
                                reactNative={{ version: '4.37.0' }}
                            />
                            {storedSampleRate == null && (
                                <Text size="xs" variant="muted" render={<span className="m-0 font-normal" />}>
                                    (default)
                                </Text>
                            )}
                        </Heading>
                        <IngestionControls.SamplingTrigger
                            initialSampleRate={toDisplaySampleRate(storedSampleRate)}
                            onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                        />
                    </div>
                    <Text size="xs" render={<p className="m-0" />}>
                        Choose how many sessions to record. 100% = record every session, 50% = record roughly half.
                    </Text>
                </div>
            </PayGateMini>
        )
    }

    return (
        <PayGateMini feature={AvailableFeature.SESSION_REPLAY_SAMPLING} featureDetail="session-replay-sampling">
            <div className="flex flex-col gap-2">
                <div className="flex flex-row justify-between items-center">
                    <LemonLabel className="text-base">
                        Sample rate{' '}
                        <Since
                            android={{ version: '3.34.0' }}
                            ios={{ version: '3.42.0' }}
                            reactNative={{ version: '4.37.0' }}
                        />
                        {storedSampleRate == null && <span className="text-muted font-normal"> (default)</span>}
                    </LemonLabel>
                    <IngestionControls.SamplingTrigger
                        initialSampleRate={toDisplaySampleRate(storedSampleRate)}
                        onChange={(v) => updateCurrentTeam({ session_recording_sample_rate: v.toString() })}
                    />
                </div>
                <p>Choose how many sessions to record. 100% = record every session, 50% = record roughly half.</p>
            </div>
        </PayGateMini>
    )
}

function MobileEventTriggers(): JSX.Element {
    const { eventTriggerConfig } = useValues(replayTriggersLogic)
    const { updateEventTriggerConfig } = useActions(replayTriggersLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                        Event emitted
                        <QuillSince
                            ios={{ version: '3.48.0' }}
                            android={{ version: '3.40.1' }}
                            reactNative={{ version: '4.52.0' }}
                            flutter={{ version: '5.25.0' }}
                        />
                    </Heading>
                    <IngestionControls.EventTriggerSelect
                        events={eventTriggerConfig}
                        onChange={updateEventTriggerConfig}
                    />
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    Start recording when a PostHog event is queued.
                </Text>
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

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    Event emitted{' '}
                    <Since
                        ios={{ version: '3.48.0' }}
                        android={{ version: '3.40.1' }}
                        reactNative={{ version: '4.52.0' }}
                        flutter={{ version: '5.25.0' }}
                    />
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

function MobileMinimumDuration(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <PayGateMini
                feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}
                featureDetail="replay-minimum-recording-duration"
            >
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                            Duration threshold
                            <QuillSince
                                ios={{ version: '3.53.0' }}
                                android={{ version: '3.44.0' }}
                                reactNative={{ version: '4.52.0' }}
                                flutter={{ version: '5.24.3' }}
                            />
                        </Heading>
                        <IngestionControls.MinDuration
                            value={currentTeam?.session_recording_minimum_duration_milliseconds}
                            onChange={(v) => updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })}
                        />
                    </div>
                    <Text size="xs" render={<p className="m-0" />}>
                        Only collect sessions that last longer than this. This helps you avoid recording sessions that
                        are too short to be useful.
                    </Text>
                </div>
            </PayGateMini>
        )
    }

    return (
        <PayGateMini
            feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}
            featureDetail="replay-minimum-recording-duration"
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-row justify-between items-center">
                    <LemonLabel className="text-base">
                        Duration threshold{' '}
                        <Since
                            ios={{ version: '3.53.0' }}
                            android={{ version: '3.44.0' }}
                            reactNative={{ version: '4.52.0' }}
                            flutter={{ version: '5.24.3' }}
                        />
                    </LemonLabel>
                    <IngestionControls.MinDuration
                        value={currentTeam?.session_recording_minimum_duration_milliseconds}
                        onChange={(v) => updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })}
                    />
                </div>
                <p>
                    Only collect sessions that last longer than this. This helps you avoid recording sessions that are
                    too short to be useful.
                </p>
            </div>
        </PayGateMini>
    )
}

function MinimumDurationSetting(): JSX.Element | null {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <PayGateMini
                feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}
                featureDetail="replay-minimum-recording-duration"
            >
                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0 flex items-center gap-1" />}>
                            Duration threshold <QuillSince web={{ version: '1.85.0' }} ios={{ version: '3.53.0' }} />
                        </Heading>
                        <IngestionControls.MinDuration
                            value={currentTeam?.session_recording_minimum_duration_milliseconds}
                            onChange={(v) => updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })}
                        />
                    </div>
                    <Text size="xs" render={<p className="m-0" />}>
                        <QuillTooltip>
                            <TooltipTrigger render={<span className="cursor-help" />}>
                                Setting a minimum session duration will ensure that only sessions that last longer than
                                that value are collected. This helps you avoid collecting sessions that are too short to
                                be useful.
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                <div className="flex flex-col gap-1">
                                    <span>
                                        The JS SDK has an in-memory queue. This means that for traditional web apps the
                                        minimum duration control is best effort.
                                    </span>
                                    <LinkPrimitive
                                        to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations"
                                        target="_blank"
                                        className="text-xs text-primary-on-foreground underline"
                                        data-ph-capture-attribute-autocapture-event-name="clicked tooltip doc link"
                                        data-ph-capture-attribute-doclink="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations"
                                    >
                                        Read the docs
                                    </LinkPrimitive>
                                </div>
                            </TooltipContent>
                        </QuillTooltip>
                    </Text>
                </div>
            </PayGateMini>
        )
    }

    return (
        <PayGateMini
            feature={AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM}
            featureDetail="replay-minimum-recording-duration"
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-row justify-between items-center">
                    <LemonLabel className="text-base">
                        Duration threshold <Since web={{ version: '1.85.0' }} ios={{ version: '3.53.0' }} />
                    </LemonLabel>
                    <IngestionControls.MinDuration
                        value={currentTeam?.session_recording_minimum_duration_milliseconds}
                        onChange={(v) => updateCurrentTeam({ session_recording_minimum_duration_milliseconds: v })}
                    />
                </div>
                <Tooltip
                    delayMs={200}
                    docLink="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations"
                    title="The JS SDK has an in-memory queue. This means that for traditional web apps the minimum duration control is best effort."
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

function LegacyRecordingConditions(): JSX.Element {
    const { selectedPlatform } = useValues(replayTriggersLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const statuses = useHeaderStatuses(currentTeam)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isV2TriggersEnabled = featureFlags[FEATURE_FLAGS.REPLAY_TRIGGERS_V2]

    if (todayRailNav) {
        return (
            <>
                {currentTeam && (
                    <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />
                )}

                <IngestionControls.MatchTypeSelect />

                <AnyWith100SamplingWarning currentTeam={currentTeam} isV2TriggersEnabled={!!isV2TriggersEnabled} />

                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Recording conditions
                    </Heading>
                    <Accordion multiple>
                        <AccordionItem value="url">
                            <AccordionTrigger>
                                <TriggerPanelHeader title="URL matches" status={statuses.urlStatus} showMatchTag />
                            </AccordionTrigger>
                            <AccordionContent>
                                <UrlTriggerOptions />
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="event">
                            <AccordionTrigger>
                                <TriggerPanelHeader title="Event emitted" status={statuses.eventStatus} showMatchTag />
                            </AccordionTrigger>
                            <AccordionContent>
                                <EventTriggerOptions />
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="flag">
                            <AccordionTrigger>
                                <TriggerPanelHeader title="Feature flag" status={statuses.flagStatus} showMatchTag />
                            </AccordionTrigger>
                            <AccordionContent>
                                <LinkedFlagSelector />
                            </AccordionContent>
                        </AccordionItem>
                    </Accordion>
                </div>

                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Recording limits
                    </Heading>
                    <Accordion multiple>
                        <AccordionItem value="sampling">
                            <AccordionTrigger>
                                <TriggerPanelHeader title="Sampling" status={statuses.samplingStatus} showMatchTag />
                            </AccordionTrigger>
                            <AccordionContent>
                                <Sampling />
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="min-duration">
                            <AccordionTrigger>
                                <TriggerPanelHeader title="Minimum duration" status={statuses.minDurationStatus} />
                            </AccordionTrigger>
                            <AccordionContent>
                                <MinimumDurationSetting />
                            </AccordionContent>
                        </AccordionItem>
                    </Accordion>
                </div>
            </>
        )
    }

    return (
        <>
            {currentTeam && <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />}

            <IngestionControls.MatchTypeSelect />

            <AnyWith100SamplingWarning currentTeam={currentTeam} isV2TriggersEnabled={!!isV2TriggersEnabled} />

            <div>
                <h3 className="text-sm font-semibold mb-2">Recording conditions</h3>
                <LemonCollapse
                    multiple
                    panels={[
                        {
                            key: 'url',
                            header: <TriggerPanelHeader title="URL matches" status={statuses.urlStatus} showMatchTag />,
                            content: <UrlTriggerOptions />,
                        },
                        {
                            key: 'event',
                            header: (
                                <TriggerPanelHeader title="Event emitted" status={statuses.eventStatus} showMatchTag />
                            ),
                            content: <EventTriggerOptions />,
                        },
                        {
                            key: 'flag',
                            header: (
                                <TriggerPanelHeader title="Feature flag" status={statuses.flagStatus} showMatchTag />
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
                                <TriggerPanelHeader title="Sampling" status={statuses.samplingStatus} showMatchTag />
                            ),
                            content: <Sampling />,
                        },
                        {
                            key: 'min-duration',
                            header: <TriggerPanelHeader title="Minimum duration" status={statuses.minDurationStatus} />,
                            content: <MinimumDurationSetting />,
                        },
                    ]}
                />
            </div>
        </>
    )
}

function RecordingExclusions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const statuses = useHeaderStatuses(currentTeam)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h3 className="m-0 flex items-center gap-1" />}>
                        Recording exclusions <QuillSince web={{ version: '1.171.0' }} />
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        The URL blocklist is global. It applies to trigger groups and to the legacy recording
                        conditions.
                    </Text>
                </div>
                <Accordion multiple>
                    <AccordionItem value="blocklist">
                        <AccordionTrigger>
                            <TriggerPanelHeader title="URL blocklist" status={statuses.blocklistStatus} />
                        </AccordionTrigger>
                        <AccordionContent>
                            <UrlBlocklistOptions />
                        </AccordionContent>
                    </AccordionItem>
                </Accordion>
            </div>
        )
    }

    return (
        <div>
            <h3 className="text-base font-semibold mb-1">
                Recording exclusions <Since web={{ version: '1.171.0' }} />
            </h3>
            <p className="text-muted text-xs mb-2">
                The URL blocklist is global. It applies to trigger groups and to the legacy recording conditions.
            </p>
            <LemonCollapse
                multiple
                panels={[
                    {
                        key: 'blocklist',
                        header: <TriggerPanelHeader title="URL blocklist" status={statuses.blocklistStatus} />,
                        content: <UrlBlocklistOptions />,
                    },
                ]}
            />
        </div>
    )
}

function SdkCompatibilityBanner(): JSX.Element {
    const {
        shouldMinimizeLegacyConditions,
        webTrafficIsRecent,
        hasV2TriggerGroups,
        hasOutdatedWebSdk,
        outdatedWebTraffic,
    } = useValues(replayTriggersLogic)
    const { hasLegacyTriggers } = useValues(replayTriggersV2Logic)
    const { showCreateFromLegacyModal, setIsAddingGroup } = useActions(replayTriggersV2Logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const trafficBannerAction = hasLegacyTriggers
        ? {
              children: 'Migrate legacy conditions',
              onClick: showCreateFromLegacyModal,
          }
        : {
              children: 'Add trigger group',
              onClick: () => setIsAddingGroup(true),
          }

    if (shouldMinimizeLegacyConditions) {
        if (todayRailNav) {
            return (
                <Item tone="success" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Your recent web SDK traffic is effectively all on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, so
                            trigger groups apply to essentially every session. The legacy recording conditions below are
                            kept only as a fallback for older SDKs.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )
        }

        return (
            <LemonBanner type="success">
                Your recent web SDK traffic is effectively all on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, so trigger groups
                apply to essentially every session. The legacy recording conditions below are kept only as a fallback
                for older SDKs.
            </LemonBanner>
        )
    }

    if (webTrafficIsRecent && !hasV2TriggerGroups) {
        if (todayRailNav) {
            return (
                <Item tone="info" size="sm" className="flex-wrap">
                    <ItemContent>
                        <ItemDescription>
                            Your recent web SDK traffic is on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, but you haven't set up
                            trigger groups yet. Recording still uses the legacy conditions below. Newer SDKs fall back
                            to them when no trigger groups exist, so nothing changes until you migrate.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={trafficBannerAction.onClick}>
                            {trafficBannerAction.children}
                        </Button>
                    </ItemActions>
                </Item>
            )
        }

        return (
            <LemonBanner type="info" action={trafficBannerAction}>
                Your recent web SDK traffic is on v{TRIGGER_GROUPS_MIN_SDK_VERSION}+, but you haven't set up trigger
                groups yet. Recording still uses the legacy conditions below. Newer SDKs fall back to them when no
                trigger groups exist, so nothing changes until you migrate.
            </LemonBanner>
        )
    }

    if (hasOutdatedWebSdk) {
        const pct = outdatedWebTraffic.share < 0.01 ? '<1' : Math.round(outdatedWebTraffic.share * 100).toString()

        if (todayRailNav) {
            return (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            About <strong>{pct}%</strong> of recent web traffic (
                            {humanFriendlyNumber(outdatedWebTraffic.outdatedCount)}{' '}
                            {pluralize(outdatedWebTraffic.outdatedCount, 'event', 'events', false)}) is on a posthog-js
                            before v{TRIGGER_GROUPS_MIN_SDK_VERSION}. Those sessions still record using the legacy
                            recording conditions below. Upgrade to v{TRIGGER_GROUPS_MIN_SDK_VERSION}+ for full
                            trigger-group coverage. Both configurations are sent meanwhile, so nothing is lost.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )
        }

        return (
            <LemonBanner type="info">
                About <strong>{pct}%</strong> of recent web traffic (
                {humanFriendlyNumber(outdatedWebTraffic.outdatedCount)}{' '}
                {pluralize(outdatedWebTraffic.outdatedCount, 'event', 'events', false)}) is on a posthog-js before v
                {TRIGGER_GROUPS_MIN_SDK_VERSION}. Those sessions still record using the legacy recording conditions
                below. Upgrade to v{TRIGGER_GROUPS_MIN_SDK_VERSION}+ for full trigger-group coverage. Both
                configurations are sent meanwhile, so nothing is lost.
            </LemonBanner>
        )
    }

    if (todayRailNav) {
        return (
            <Item tone="warning" size="sm">
                <ItemContent>
                    <ItemTitle>JavaScript SDK version compatibility</ItemTitle>
                    <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs">
                        <li>
                            SDK versions &gt;= v{TRIGGER_GROUPS_MIN_SDK_VERSION} use trigger groups if configured,
                            otherwise fall back to the legacy recording conditions
                        </li>
                        <li>
                            Both configurations are sent to ensure backward compatibility with all JavaScript SDK
                            versions
                        </li>
                    </ul>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="warning">
            <strong>JavaScript SDK version compatibility</strong>
            <ul className="list-disc ml-4 mt-2 space-y-1">
                <li>
                    SDK versions &gt;= v{TRIGGER_GROUPS_MIN_SDK_VERSION} use trigger groups if configured, otherwise
                    fall back to the legacy recording conditions
                </li>
                <li>Both configurations are sent to ensure backward compatibility with all JavaScript SDK versions</li>
            </ul>
        </LemonBanner>
    )
}

export function ReplayTriggers(): JSX.Element {
    const { selectedPlatform, shouldMinimizeLegacyConditions } = useValues(replayTriggersLogic)
    const { selectPlatform } = useActions(replayTriggersLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isV2TriggersEnabled = featureFlags[FEATURE_FLAGS.REPLAY_TRIGGERS_V2]

    const handleMatchTypeChange = (value: 'any' | 'all'): void =>
        updateCurrentTeam({ session_recording_trigger_match_type_config: value })

    if (todayRailNav) {
        return (
            <IngestionControls
                logicKey="session-replay"
                resourceType={AccessControlResourceType.SessionRecording}
                matchType={currentTeam?.session_recording_trigger_match_type_config || 'all'}
                onChangeMatchType={handleMatchTypeChange}
            >
                <Tabs value={selectedPlatform} onValueChange={(platform) => selectPlatform(platform as ReplayPlatform)}>
                    <TabsList variant="line">
                        <TabsTrigger value="web">Web</TabsTrigger>
                        <TabsTrigger value="mobile">Mobile</TabsTrigger>
                    </TabsList>
                    <TabsContent value="web">
                        <div className="flex flex-col gap-4">
                            {isV2TriggersEnabled && (
                                <>
                                    <SdkCompatibilityBanner />

                                    <TriggerGroupsEditor />
                                </>
                            )}

                            <RecordingExclusions />

                            {isV2TriggersEnabled && (
                                <div className="flex flex-col gap-4 pt-2">
                                    <Separator />
                                    <Heading size="sm" render={<h3 className="m-0" />}>
                                        Legacy recording conditions
                                    </Heading>
                                </div>
                            )}

                            {isV2TriggersEnabled && shouldMinimizeLegacyConditions ? (
                                <Accordion>
                                    <AccordionItem value="legacy-recording-conditions">
                                        <AccordionTrigger>
                                            <Text
                                                size="xs"
                                                variant="muted"
                                                render={<span className="m-0 font-normal" />}
                                            >
                                                Hidden because your web SDKs (v{TRIGGER_GROUPS_MIN_SDK_VERSION}+) use
                                                trigger groups. Expand to configure fallbacks for older SDK versions.
                                            </Text>
                                        </AccordionTrigger>
                                        <AccordionContent>
                                            <div className="flex flex-col gap-4">
                                                <LegacyRecordingConditions />
                                            </div>
                                        </AccordionContent>
                                    </AccordionItem>
                                </Accordion>
                            ) : (
                                <>
                                    {isV2TriggersEnabled && (
                                        <Item tone="warning" size="sm">
                                            <ItemContent>
                                                <ItemDescription>
                                                    Used by SDK versions &lt; v{TRIGGER_GROUPS_MIN_SDK_VERSION} and as
                                                    fallback for newer versions if trigger groups are not configured.
                                                </ItemDescription>
                                            </ItemContent>
                                        </Item>
                                    )}
                                    <LegacyRecordingConditions />
                                </>
                            )}
                        </div>
                    </TabsContent>
                    <TabsContent value="mobile">
                        <div className="flex flex-col gap-2">
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        Trigger groups aren't available on mobile yet. Mobile recording uses the
                                        settings below, which are shared with web. Changing a setting here also changes
                                        it on web.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                            {currentTeam && (
                                <RecordingTriggersSummary
                                    currentTeam={currentTeam}
                                    selectedPlatform={selectedPlatform}
                                />
                            )}
                            <IngestionControls.MatchTypeSelect lockedToAllReason="Mobile only supports trigger matching of type 'all'." />
                            <MobileEventTriggers />
                            <LinkedFlagSelector />
                            <MobileSampling />
                            <MobileMinimumDuration />
                        </div>
                    </TabsContent>
                </Tabs>
            </IngestionControls>
        )
    }

    const tabs: LemonTab<'web' | 'mobile'>[] = [
        {
            key: 'web',
            label: 'Web',
            content: (
                <div className="flex flex-col gap-y-4">
                    {isV2TriggersEnabled && (
                        <>
                            <SdkCompatibilityBanner />

                            <TriggerGroupsEditor />
                        </>
                    )}

                    <RecordingExclusions />

                    {isV2TriggersEnabled && (
                        <div className="mt-2">
                            <LemonDivider className="mb-4" />
                            <h3 className="text-base font-semibold mb-1">Legacy recording conditions</h3>
                        </div>
                    )}

                    {isV2TriggersEnabled && shouldMinimizeLegacyConditions ? (
                        <LemonCollapse
                            panels={[
                                {
                                    key: 'legacy-recording-conditions',
                                    header: (
                                        <span className="text-muted text-sm font-normal">
                                            Hidden because your web SDKs (v{TRIGGER_GROUPS_MIN_SDK_VERSION}+) use
                                            trigger groups. Expand to configure fallbacks for older SDK versions.
                                        </span>
                                    ),
                                    content: (
                                        <div className="flex flex-col gap-y-4 pt-2">
                                            <LegacyRecordingConditions />
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    ) : (
                        <>
                            {isV2TriggersEnabled && (
                                <LemonBanner type="warning">
                                    Used by SDK versions &lt; v{TRIGGER_GROUPS_MIN_SDK_VERSION} and as fallback for
                                    newer versions if trigger groups are not configured.
                                </LemonBanner>
                            )}
                            <LegacyRecordingConditions />
                        </>
                    )}
                </div>
            ),
        },
        {
            key: 'mobile',
            label: 'Mobile',
            content: (
                <div className="flex flex-col gap-y-2">
                    <LemonBanner type="info">
                        Trigger groups aren't available on mobile yet. Mobile recording uses the settings below, which
                        are shared with web. Changing a setting here also changes it on web.
                    </LemonBanner>
                    {currentTeam && (
                        <RecordingTriggersSummary currentTeam={currentTeam} selectedPlatform={selectedPlatform} />
                    )}
                    <IngestionControls.MatchTypeSelect lockedToAllReason="Mobile only supports trigger matching of type 'all'." />
                    <MobileEventTriggers />
                    <LinkedFlagSelector />
                    <MobileSampling />
                    <MobileMinimumDuration />
                </div>
            ),
        },
    ]

    return (
        <IngestionControls
            logicKey="session-replay"
            resourceType={AccessControlResourceType.SessionRecording}
            matchType={currentTeam?.session_recording_trigger_match_type_config || 'all'}
            onChangeMatchType={handleMatchTypeChange}
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeam?.session_recording_opt_in) {
        if (todayRailNav) {
            return (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            <strong>Recording is disabled.</strong> Enable it in General settings.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )
        }

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
            minDurationMs: hasMinDuration ? (currentTeam.session_recording_minimum_duration_milliseconds ?? 0) : null,
        },
    ]
}
