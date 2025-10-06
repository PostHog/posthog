import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    LemonSnack,
    LemonTag,
    Link,
    Popover,
    Spinner,
    lemonToast,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconCancel } from 'lib/lemon-ui/icons'
import { AiRegexHelper, AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { SupportedPlatforms } from 'scenes/settings/environment/SessionRecordingSettings'
import { isStringWithLength, replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'
import { sessionReplayIngestionControlLogic } from 'scenes/settings/environment/sessionReplayIngestionControlLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { SelectOption } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { AccessControlLevel, AccessControlResourceType, AvailableFeature, MultivariateFlagOptions } from '~/types'
import { SessionReplayUrlTriggerConfig } from '~/types'

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
            <div className="flex flex-col deprecated-space-y-2 mt-2">
                <div className="flex justify-between">
                    <LemonLabel className="text-base">
                        <TriggerMatchTypeTag /> Enable recordings using feature flag {featureFlagLoading && <Spinner />}
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
                                    disabledReason={disabledReason ?? undefined}
                                    readOnly={!!disabledReason}
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
                                />
                            </AccessControlAction>
                        )}
                    </div>
                </div>
                <SupportedPlatforms
                    web={{ version: '1.110.0' }}
                    ios={{ version: '3.11.0' }}
                    android={{ version: '3.11.0' }}
                    reactNative={{ version: '3.6.3' }}
                    flutter={{ version: '4.7.0' }}
                />
                <p>Linking a flag means that recordings will only be collected for users who have the flag enabled.</p>
                {flagHasVariants && (
                    <>
                        <LemonLabel className="text-base">Link to a specific flag variant</LemonLabel>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.SessionRecording}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {({ disabledReason }) => (
                                <LemonSegmentedButton
                                    className="min-w-1/3"
                                    value={currentTeam?.session_recording_linked_flag?.variant ?? ANY_VARIANT}
                                    options={variantOptions(linkedFlag?.filters.multivariate, disabledReason)}
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

function UrlConfigForm({
    type,
    onCancel,
    isSubmitting,
}: {
    type: 'trigger' | 'blocklist'
    onCancel: () => void
    isSubmitting: boolean
}): JSX.Element {
    const { addUrlTrigger, addUrlBlocklist } = useActions(replayTriggersLogic)

    return (
        <Form
            logic={replayTriggersLogic}
            formKey={type === 'trigger' ? 'proposedUrlTrigger' : 'proposedUrlBlocklist'}
            enableFormOnSubmit
            className="w-full flex flex-col border rounded items-center p-2 pl-4 bg-surface-primary gap-2"
        >
            <div className="flex flex-col gap-2 w-full">
                <LemonBanner type="info" className="text-sm">
                    We always wrap the URL regex with anchors to avoid unexpected behavior (if you do not). This is
                    because <pre className="inline">https://example.com/</pre> does not only match the homepage. You'd
                    need <pre className="inline">^https://example.com/$</pre>
                </LemonBanner>
                <LemonLabel className="w-full">
                    Matching regex:
                    <LemonField name="url" className="flex-1">
                        <LemonInput autoFocus placeholder="Enter URL regex." data-attr="url-input" />
                    </LemonField>
                </LemonLabel>
            </div>
            <div className="flex justify-between gap-2 w-full">
                <div>
                    <AiRegexHelper
                        onApply={(regex) => {
                            try {
                                const payload: SessionReplayUrlTriggerConfig = {
                                    url: regex,
                                    matching: 'regex',
                                }
                                if (type === 'trigger') {
                                    addUrlTrigger(payload)
                                } else {
                                    addUrlBlocklist(payload)
                                }
                            } catch {
                                lemonToast.error('Failed to apply regex')
                            }
                        }}
                    />
                    <AiRegexHelperButton />
                </div>

                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        htmlType="submit"
                        type="primary"
                        disabledReason={isSubmitting ? `Saving url in progress` : undefined}
                        data-attr="url-save"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

function UrlConfigRow({
    trigger,
    index,
    type,
    editIndex,
    onEdit,
    onRemove,
}: {
    trigger: SessionReplayUrlTriggerConfig
    index: number
    type: 'trigger' | 'blocklist'
    editIndex: number | null
    onEdit: (index: number) => void
    onRemove: (index: number) => void
}): JSX.Element {
    if (editIndex === index) {
        return (
            <div className="border rounded p-2 bg-surface-primary">
                <UrlConfigForm type={type} onCancel={() => onEdit(-1)} isSubmitting={false} />
            </div>
        )
    }

    return (
        <div className={clsx('border rounded flex items-center p-2 pl-4 bg-surface-primary')}>
            <span title={trigger.url} className="flex-1 truncate">
                <span>{trigger.matching === 'regex' ? 'Matches regex: ' : ''}</span>
                <span>{trigger.url}</span>
            </span>
            <div className="Actions flex deprecated-space-x-1 shrink-0">
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton icon={<IconPencil />} onClick={() => onEdit(index)} tooltip="Edit" center>
                        Edit
                    </LemonButton>
                </AccessControlAction>

                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        icon={<IconTrash />}
                        tooltip={`Remove URL ${type}`}
                        center
                        onClick={() => {
                            LemonDialog.open({
                                title: <>Remove URL {type}</>,
                                description: `Are you sure you want to remove this URL ${type}?`,
                                primaryButton: {
                                    status: 'danger',
                                    children: 'Remove',
                                    onClick: () => onRemove(index),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        }}
                    >
                        Remove
                    </LemonButton>
                </AccessControlAction>
            </div>
        </div>
    )
}

function UrlConfigSection({
    type,
    title,
    description,
    ...props
}: {
    type: 'trigger' | 'blocklist'
    title: string
    description: string
    isAddFormVisible: boolean
    config: SessionReplayUrlTriggerConfig[] | null
    editIndex: number | null
    isSubmitting: boolean
    onAdd: () => void
    onCancel: () => void
    onEdit: (index: number) => void
    onRemove: (index: number) => void
}): JSX.Element {
    return (
        <div className="flex flex-col deprecated-space-y-2 mt-4">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">{title}</LemonLabel>
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        onClick={props.onAdd}
                        type="secondary"
                        icon={<IconPlus />}
                        data-attr={`session-replay-add-url-${type}`}
                    >
                        Add
                    </LemonButton>
                </AccessControlAction>
            </div>
            <SupportedPlatforms
                android={false}
                ios={false}
                flutter={false}
                web={{ version: '1.171.0' }}
                reactNative={false}
            />
            <p>{description}</p>

            {props.isAddFormVisible && (
                <UrlConfigForm type={type} onCancel={props.onCancel} isSubmitting={props.isSubmitting} />
            )}
            {props.config?.map((trigger, index) => (
                <UrlConfigRow
                    key={`${trigger.url}-${trigger.matching}`}
                    trigger={trigger}
                    index={index}
                    type={type}
                    editIndex={props.editIndex}
                    onEdit={props.onEdit}
                    onRemove={props.onRemove}
                />
            ))}
        </div>
    )
}

function UrlTriggerOptions(): JSX.Element | null {
    const { isAddUrlTriggerConfigFormVisible, urlTriggerConfig, editUrlTriggerIndex, isProposedUrlTriggerSubmitting } =
        useValues(replayTriggersLogic)
    const { newUrlTrigger, removeUrlTrigger, setEditUrlTriggerIndex, cancelProposingUrlTrigger } =
        useActions(replayTriggersLogic)

    return (
        <UrlConfigSection
            type="trigger"
            title="Enable recordings when URL matches"
            description="Adding a URL trigger means recording will only be started when the user visits a page that matches the URL."
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
    } = useValues(replayTriggersLogic)
    const { newUrlBlocklist, removeUrlBlocklist, setEditUrlBlocklistIndex, cancelProposingUrlBlocklist } =
        useActions(replayTriggersLogic)

    return (
        <UrlConfigSection
            type="blocklist"
            title="Pause recordings when the user visits a page that matches the URL"
            description="Used to pause recordings for part of a user journey"
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
            <AccessControlAction
                resourceType={AccessControlResourceType.SessionRecording}
                minAccessLevel={AccessControlLevel.Editor}
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
            </AccessControlAction>
        </Popover>
    )
}

function EventTriggerOptions(): JSX.Element | null {
    const { eventTriggerConfig } = useValues(replayTriggersLogic)
    const { updateEventTriggerConfig } = useActions(replayTriggersLogic)

    return (
        <div className="flex flex-col deprecated-space-y-2 mt-2">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">
                    <TriggerMatchTypeTag /> Event emitted
                </LemonLabel>
                <EventSelectButton />
            </div>
            <SupportedPlatforms
                android={false}
                ios={false}
                flutter={false}
                web={{ version: '1.186.0' }}
                reactNative={false}
            />
            <div className="flex gap-2">
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
                    <TriggerMatchTypeTag /> Sampling
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
            <SupportedPlatforms web={{ version: '1.85.0' }} />
            <p>
                Use this setting to restrict the percentage of sessions that will be recorded. This is useful if you
                want to reduce the amount of data you collect. 100% means all sessions will be collected. 50% means
                roughly half of sessions will be collected.
            </p>
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
                    <LemonLabel className="text-base">Minimum session duration (seconds)</LemonLabel>
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
                <SupportedPlatforms web={{ version: '1.85.0' }} />
                <p>
                    Setting a minimum session duration will ensure that only sessions that last longer than that value
                    are collected. This helps you avoid collecting sessions that are too short to be useful.
                </p>
                <p>
                    The JS SDK has an in-memory queue. This means that for traditional web apps the minimum duration
                    control is best effort.{' '}
                    <Link to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record#limitations">
                        Read more in our docs
                    </Link>
                </p>
            </>
        </PayGateMini>
    )
}

function TriggerMatchChoice(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="flex flex-col gap-y-1">
            <LemonLabel className="text-base py-2">Trigger matching</LemonLabel>
            <SupportedPlatforms web={{ version: '1.238.0' }} />
            <LemonBanner type="info" className="text-sm" hideIcon={true} dismissKey="replay-trigger-match-1-238-0">
                <div className="flex flex-row gap-x-4 items-center">
                    <LemonTag type="warning">NEW</LemonTag>
                    <div>
                        <strong>Trigger matching</strong>
                        <p>
                            From version 1.238.0 of posthog-js on web, you can choose between "all" and "any" for
                            trigger matching.
                        </p>
                        <p>For example if you set 30% sampling and an event trigger for exceptions:</p>
                        <ul>
                            <li className="my-1">
                                With "ALL" trigger matching, only 30% of sessions with exceptions will be recorded.
                            </li>
                            <li>
                                With "ANY" trigger matching, 30% of all sessions will be recorded, and 100% of sessions
                                that have exceptions will be recorded.
                            </li>
                        </ul>
                    </div>
                </div>
            </LemonBanner>
            <div className="flex flex-row gap-x-2 items-center">
                <div>Start when</div>
                <AccessControlAction
                    resourceType={AccessControlResourceType.SessionRecording}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonSelect
                        options={[
                            {
                                label: 'all',
                                value: 'all',
                                labelInMenu: (
                                    <SelectOption
                                        title="All"
                                        description="Every trigger must match"
                                        value="all"
                                        selectedValue={
                                            currentTeam?.session_recording_trigger_match_type_config || 'all'
                                        }
                                    />
                                ),
                            },
                            {
                                label: 'any',
                                value: 'any',
                                labelInMenu: (
                                    <SelectOption
                                        title="Any"
                                        description="One or more triggers must match"
                                        value="any"
                                        selectedValue={
                                            currentTeam?.session_recording_trigger_match_type_config || 'all'
                                        }
                                    />
                                ),
                            },
                        ]}
                        dropdownMatchSelectWidth={false}
                        data-attr="trigger-match-choice"
                        onChange={(value) => {
                            updateCurrentTeam({ session_recording_trigger_match_type_config: value })
                        }}
                        value={currentTeam?.session_recording_trigger_match_type_config || 'all'}
                    />
                </AccessControlAction>

                <div>triggers below match</div>
            </div>
        </div>
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
    return (
        <div className="deprecated-space-y-2">
            <p>
                Use the settings below to control when recordings are started. If no triggers are selected, then
                recordings will always start if enabled.
            </p>
            <p>
                PostHog offers several tools to let you control the number of recordings you collect and which users you
                collect recordings for.{' '}
                <Link
                    to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record"
                    target="blank"
                >
                    Learn more in our docs.
                </Link>
            </p>

            <div className="border rounded py-2 px-4">
                <TriggerMatchChoice />
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
    )
}
