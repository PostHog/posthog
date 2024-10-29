import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonSelect,
    Link,
    Spinner,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FlagSelector } from 'lib/components/FlagSelector'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { FEATURE_FLAGS, SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { sessionReplayIngestionControlLogic } from 'scenes/settings/environment/sessionReplayIngestionControlLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, MultivariateFlagOptions, SessionReplayUrlTriggerConfig } from '~/types'

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
            <div className="flex flex-col space-y-2">
                <LemonLabel className="text-base">
                    Enable recordings using feature flag {featureFlagLoading && <Spinner />}
                </LemonLabel>
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

function UrlConfigForm({
    type,
    onCancel,
    isSubmitting,
}: {
    type: 'trigger' | 'blocklist'
    onCancel: () => void
    isSubmitting: boolean
}): JSX.Element {
    return (
        <Form
            logic={sessionReplayIngestionControlLogic}
            formKey={type === 'trigger' ? 'proposedUrlTrigger' : 'proposedUrlBlocklist'}
            enableFormOnSubmit
            className="w-full flex flex-col border rounded items-center p-2 pl-4 bg-bg-light gap-2"
        >
            <div className="flex flex-row gap-2 w-full">
                <LemonField name="matching">
                    <LemonSelect options={[{ label: 'Regex', value: 'regex' }]} />
                </LemonField>
                <LemonField name="url" className="flex-1">
                    <LemonInput autoFocus placeholder="Enter URL" data-attr="url-input" />
                </LemonField>
            </div>
            <div className="flex justify-end gap-2 w-full">
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
        </Form>
    )
}

// New shared row component
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
            <div className="border rounded p-2 bg-bg-light">
                <UrlConfigForm type={type} onCancel={() => onEdit(-1)} isSubmitting={false} />
            </div>
        )
    }

    return (
        <div className={clsx('border rounded flex items-center p-2 pl-4 bg-bg-light')}>
            <span title={trigger.url} className="flex-1 truncate">
                {trigger.matching === 'regex' ? 'Matches regex: ' : ''} {trigger.url}
            </span>
            <div className="Actions flex space-x-1 shrink-0">
                <LemonButton icon={<IconPencil />} onClick={() => onEdit(index)} tooltip="Edit" center />
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
                />
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
        <div className="flex flex-col space-y-2 mt-4">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">{title}</LemonLabel>
                <LemonButton
                    onClick={props.onAdd}
                    type="secondary"
                    icon={<IconPlus />}
                    data-attr={`session-replay-add-url-${type}`}
                >
                    Add
                </LemonButton>
            </div>
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
        useValues(sessionReplayIngestionControlLogic)
    const { newUrlTrigger, removeUrlTrigger, setEditUrlTriggerIndex, cancelProposingUrlTrigger } = useActions(
        sessionReplayIngestionControlLogic
    )

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
    } = useValues(sessionReplayIngestionControlLogic)
    const { newUrlBlocklist, removeUrlBlocklist, setEditUrlBlocklistIndex, cancelProposingUrlBlocklist } = useActions(
        sessionReplayIngestionControlLogic
    )

    return (
        <UrlConfigSection
            type="blocklist"
            title="Block recordings when URL matches"
            description="Adding a URL blocklist means recording will be paused when the user visits a page that matches the URL."
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
                        <p>
                            Use this setting to restrict the percentage of sessions that will be recorded. This is
                            useful if you want to reduce the amount of data you collect. 100% means all sessions will be
                            collected. 50% means roughly half of sessions will be collected.
                        </p>
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
                        <p>
                            Setting a minimum session duration will ensure that only sessions that last longer than that
                            value are collected. This helps you avoid collecting sessions that are too short to be
                            useful.
                        </p>
                    </>
                )}
                <LinkedFlagSelector />
                <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_URL_TRIGGER}>
                    <UrlTriggerOptions />
                </FlaggedFeature>
                <FlaggedFeature flag={FEATURE_FLAGS.SESSION_REPLAY_URL_BLOCKLIST}>
                    <UrlBlocklistOptions />
                </FlaggedFeature>
            </>
        </PayGateMini>
    )
}
