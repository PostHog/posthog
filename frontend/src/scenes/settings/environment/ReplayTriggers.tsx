import { IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { EventSelect } from 'lib/components/EventSelect/EventSelect'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { AiRegexHelper, AiRegexHelperButton } from 'scenes/session-recordings/components/AiRegexHelper/AiRegexHelper'
import { replayTriggersLogic } from 'scenes/settings/environment/replayTriggersLogic'
import { SupportedPlatforms } from 'scenes/settings/environment/SessionRecordingSettings'

import { SessionReplayUrlTriggerConfig } from '~/types'

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
                    <FlaggedFeature flag={FEATURE_FLAGS.RECORDINGS_AI_REGEX}>
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
                                } catch (error) {
                                    lemonToast.error('Failed to apply regex')
                                }
                            }}
                        />
                        <AiRegexHelperButton />
                    </FlaggedFeature>
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
        <div className="flex flex-col deprecated-space-y-2 mt-4">
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
            title="Pause recordings when URL matches"
            description="Recording will be paused when the user visits a page that matches the URL."
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
        <div className="flex flex-col deprecated-space-y-2 mt-4">
            <div className="flex items-center gap-2 justify-between">
                <LemonLabel className="text-base">Event emitted</LemonLabel>
            </div>
            <p>
                Session recording will be started immediately before PostHog queues any of these events to be sent to
                the backend.
            </p>

            <EventSelect
                filterGroupTypes={[TaxonomicFilterGroupType.Events]}
                onChange={(includedEvents) => {
                    updateEventTriggerConfig(includedEvents)
                }}
                selectedEvents={eventTriggerConfig ?? []}
                addElement={
                    <LemonButton size="small" type="secondary" icon={<IconPlus />} sideIcon={null}>
                        Add event
                    </LemonButton>
                }
            />
        </div>
    )
}

export function ReplayTriggers(): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <SupportedPlatforms
                android={false}
                ios={false}
                flutter={false}
                web={{ version: '1.186.0', note: 'url trigger is supported since version 1.171.0' }}
                reactNative={false}
            />
            <p>
                Use the settings below to control when recordings are started or paused. If no triggers are selected,
                then recordings will always start if enabled.
            </p>
            <LemonBanner type="info">
                Session recording triggers work as OR conditions — the recording starts if <i>any</i> of the set
                triggers (URL or event) are matched.
            </LemonBanner>
            <UrlTriggerOptions />
            <UrlBlocklistOptions />
            <EventTriggerOptions />
        </div>
    )
}
