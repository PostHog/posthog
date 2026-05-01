import { useValues, useActions } from 'kea'
import { Form } from 'kea-forms'

import { IconChevronDown, IconFilter, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonSnack,
    LemonTag,
} from '@posthog/lemon-ui'

import { FlagSelector } from 'lib/components/FlagSelector'
import { EventTriggerSelect } from 'lib/components/IngestionControls/triggers/EventTrigger'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { TRIGGER_GROUPS_MIN_SDK_VERSION } from 'scenes/settings/environment/ReplayTriggers'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import {
    EventTriggerConfig,
    SessionRecordingTriggerGroup,
    TriggerPropertyFilter,
} from '~/lib/components/IngestionControls/types'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { CreateFromLegacyModal } from './CreateFromLegacyModal'
import { replayTriggersV2Logic } from './replayTriggersV2Logic'
import { TriggerGroupCard } from './TriggerGroupCard'
import { triggerGroupFormLogic } from './triggerGroupFormLogic'

/** Operators supported by the SDK for trigger property evaluation */
const SUPPORTED_OPERATORS: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
    PropertyOperator.GreaterThan,
    PropertyOperator.LessThan,
]

/** Convert our trigger property filters to the AnyPropertyFilter format PropertyFilters component expects */
function triggerFiltersToPropertyFilters(filters: TriggerPropertyFilter[]): AnyPropertyFilter[] {
    return filters.map(
        (f) =>
            ({
                key: f.key,
                type: f.type === 'person' ? PropertyFilterType.Person : PropertyFilterType.Event,
                operator: (f.operator as PropertyOperator) || PropertyOperator.Exact,
                value: f.value ?? '',
            }) as AnyPropertyFilter
    )
}

/** Convert PropertyFilters output back to our trigger property filter format */
function propertyFiltersToTriggerFilters(filters: AnyPropertyFilter[]): TriggerPropertyFilter[] {
    return filters
        .filter((f) => f.key)
        .map((f) => ({
            key: f.key!,
            type: f.type === PropertyFilterType.Person ? ('person' as const) : ('event' as const),
            operator: 'operator' in f ? (f.operator as TriggerPropertyFilter['operator']) : 'exact',
            value: 'value' in f ? (f.value as TriggerPropertyFilter['value']) : undefined,
        }))
}

export function TriggerGroupsEditor(): JSX.Element {
    const {
        triggerGroups,
        isAddingGroup,
        editingGroupId,
        deleteModalGroupId,
        showLegacyModal,
        previewLegacyGroups,
        _savingStateLoading,
        shouldShowMigrationBanner,
    } = useValues(replayTriggersV2Logic)
    const {
        addTriggerGroup,
        updateTriggerGroup,
        deleteTriggerGroup,
        setIsAddingGroup,
        setEditingGroupId,
        setDeleteModalGroupId,
        showCreateFromLegacyModal,
        hideCreateFromLegacyModal,
        confirmCreateFromLegacy,
    } = useActions(replayTriggersV2Logic)

    const handleDeleteTriggerGroup = (id: string): void => {
        if (triggerGroups.length === 1) {
            setDeleteModalGroupId(id)
        } else {
            // Standard confirmation for non-last groups
            const group = triggerGroups.find((g) => g.id === id)
            const displayName = group?.name || `Trigger group ${id.slice(0, 8)}`

            LemonDialog.open({
                title: 'Delete trigger group?',
                description: `Are you sure you want to delete "${displayName}"? This cannot be undone.`,
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: () => deleteTriggerGroup(id),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <LemonLabel className="text-base py-2">
                        Trigger groups
                        <Since web={{ version: TRIGGER_GROUPS_MIN_SDK_VERSION }} />
                    </LemonLabel>
                </div>
                {!isAddingGroup && !editingGroupId && (
                    <div className="flex gap-2">
                        {triggerGroups.length === 0 && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={showCreateFromLegacyModal}
                                data-attr="trigger-group-migrate-from-legacy"
                            >
                                Migrate from legacy recording conditions
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            size="small"
                            onClick={() => setIsAddingGroup(true)}
                            data-attr="trigger-group-add"
                        >
                            Add
                        </LemonButton>
                    </div>
                )}
            </div>

            <p className="text-xs text-muted">
                Configure custom recording triggers with individual sampling rates per group. Recording will start if
                any of the recording trigger groups match.
            </p>

            {shouldShowMigrationBanner && (
                <LemonBanner type="info">
                    <strong>You're using legacy recording triggers</strong>
                    <p className="mt-1">
                        Trigger groups offer more flexibility, including individual sampling rates per group. Migrate
                        your existing configuration by clicking the migrate button above.
                    </p>
                </LemonBanner>
            )}

            {isAddingGroup && (
                <GroupForm
                    onSave={(group) => {
                        addTriggerGroup(group)
                    }}
                    onCancel={() => setIsAddingGroup(false)}
                />
            )}

            {triggerGroups.length === 0 && !isAddingGroup ? (
                <div className="border border-dashed rounded p-6 text-center text-muted">
                    <p>No trigger groups configured</p>
                    <p className="text-xs mt-2">Add a group to start recording based on specific conditions.</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {triggerGroups.map((group: SessionRecordingTriggerGroup, index: number) => (
                        <div key={group.id}>
                            {index > 0 && (
                                <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                                    OR
                                </div>
                            )}
                            {editingGroupId === group.id ? (
                                <GroupForm
                                    group={group}
                                    onSave={(updatedGroup) => {
                                        updateTriggerGroup(updatedGroup.id, updatedGroup)
                                    }}
                                    onCancel={() => setEditingGroupId(null)}
                                />
                            ) : (
                                <TriggerGroupCard
                                    group={group}
                                    onEdit={() => setEditingGroupId(group.id)}
                                    onDelete={handleDeleteTriggerGroup}
                                />
                            )}
                        </div>
                    ))}
                </div>
            )}

            <CreateFromLegacyModal
                isOpen={showLegacyModal}
                onClose={hideCreateFromLegacyModal}
                onConfirm={confirmCreateFromLegacy}
                previewGroups={previewLegacyGroups}
                isCreating={_savingStateLoading}
            />

            <DeleteLastGroupModal
                isOpen={!!deleteModalGroupId}
                onClose={() => setDeleteModalGroupId(null)}
                onConfirm={() => {
                    if (deleteModalGroupId) {
                        deleteTriggerGroup(deleteModalGroupId)
                    }
                }}
                groupName={
                    triggerGroups.find((g) => g.id === deleteModalGroupId)?.name ||
                    `Trigger group ${deleteModalGroupId?.slice(0, 8)}`
                }
            />
        </div>
    )
}

interface GroupFormProps {
    group?: SessionRecordingTriggerGroup
    onSave: (group: SessionRecordingTriggerGroup) => void
    onCancel: () => void
}

function EventTriggerRow({
    event,
    isExpanded,
    onToggle,
    onRemove,
    onUpdateProperties,
}: {
    event: EventTriggerConfig
    isExpanded: boolean
    onToggle: () => void
    onRemove: () => void
    onUpdateProperties: (properties: TriggerPropertyFilter[]) => void
}): JSX.Element {
    const hasProperties = event.properties && event.properties.length > 0

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center gap-2 p-2 pl-3">
                <LemonButton
                    size="xsmall"
                    icon={<IconChevronDown className={`transition-transform ${isExpanded ? '' : '-rotate-90'}`} />}
                    onClick={onToggle}
                />
                <span className="flex-1 text-sm font-medium">{event.name}</span>
                {hasProperties && (
                    <span className="text-xs text-muted flex items-center gap-1">
                        <IconFilter className="w-3 h-3" />
                        {event.properties!.length} filter{event.properties!.length !== 1 ? 's' : ''}
                    </span>
                )}
                <LemonButton size="xsmall" status="danger" onClick={onRemove}>
                    Remove
                </LemonButton>
            </div>
            {isExpanded && (
                <div className="border-t p-3 bg-bg-3000">
                    <div className="text-xs font-medium text-muted mb-2 uppercase tracking-wide">
                        Per-event property filters
                    </div>
                    <div className="text-xs text-muted mb-2">
                        Only trigger on this event when these conditions are met.
                    </div>
                    <PropertyFilters
                        propertyFilters={triggerFiltersToPropertyFilters(event.properties || [])}
                        onChange={(filters) => onUpdateProperties(propertyFiltersToTriggerFilters(filters))}
                        pageKey={`trigger-event-${event.name}`}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                        ]}
                        eventNames={[event.name]}
                        buttonText="Add property filter"
                        buttonSize="small"
                        operatorAllowlist={SUPPORTED_OPERATORS}
                    />
                </div>
            )}
        </div>
    )
}

function GroupForm({ group, onSave, onCancel }: GroupFormProps): JSX.Element {
    const logic = triggerGroupFormLogic({ group, onSave, onCancel })
    const { triggerGroup, isAddingUrl, newUrl, testUrl, isTriggerGroupSubmitting, expandedEvent } = useValues(logic)
    const {
        setTriggerGroupValue,
        setIsAddingUrl,
        setNewUrl,
        setTestUrl,
        addUrl,
        removeUrl,
        removeEvent,
        addFlag,
        removeFlag,
        setEventProperties,
        setExpandedEvent,
    } = useActions(logic)

    const handleAddEvent = (events: string[]): void => {
        const existingNames = new Set(triggerGroup.events.map((e) => e.name))
        const newEvents = events.filter((name) => !existingNames.has(name)).map((name) => ({ name }))
        setTriggerGroupValue('events', [...triggerGroup.events, ...newEvents])
    }

    return (
        <Form
            logic={triggerGroupFormLogic}
            props={{ group, onSave, onCancel }}
            formKey="triggerGroup"
            enableFormOnSubmit
        >
            <div className="border rounded p-4 bg-surface-primary space-y-4">
                <LemonField name="name" label="Group name">
                    <LemonInput placeholder="e.g., Error Tracking, Feature Testing" fullWidth />
                </LemonField>

                <div className="flex gap-4">
                    <div className="flex-1">
                        <LemonField name="sampleRate" label="Sample rate (%)">
                            <LemonInput type="number" min={0} max={100} fullWidth />
                        </LemonField>
                    </div>

                    <div className="flex-1">
                        <LemonField name="minDurationMs" label="Minimum duration (seconds)">
                            <LemonSelect options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS} fullWidth />
                        </LemonField>
                    </div>
                </div>

                <LemonField name="matchType" label="Match type">
                    <LemonSelect
                        options={[
                            { value: 'any', label: 'ANY condition matches' },
                            { value: 'all', label: 'ALL conditions match' },
                        ]}
                        fullWidth
                    />
                </LemonField>

                <div className="border-t pt-3">
                    <h5 className="font-semibold mb-3">Conditions</h5>

                    {/* Events */}
                    <div className="mb-4">
                        <div className="flex items-center gap-2 justify-between mb-2">
                            <LemonLabel>Event triggers</LemonLabel>
                            <EventTriggerSelect
                                events={triggerGroup.events.map((e) => e.name)}
                                onChange={handleAddEvent}
                            />
                        </div>
                        {triggerGroup.events.length > 0 && (
                            <div className="space-y-2">
                                {triggerGroup.events.map((event) => (
                                    <EventTriggerRow
                                        key={event.name}
                                        event={event}
                                        isExpanded={expandedEvent === event.name}
                                        onToggle={() =>
                                            setExpandedEvent(expandedEvent === event.name ? null : event.name)
                                        }
                                        onRemove={() => removeEvent(event.name)}
                                        onUpdateProperties={(properties) => setEventProperties(event.name, properties)}
                                    />
                                ))}
                            </div>
                        )}
                    </div>

                    {/* URLs */}
                    <div className="mb-4">
                        <div className="flex items-center gap-2 justify-between mb-2">
                            <div>
                                <LemonLabel>URL patterns (regex)</LemonLabel>
                                <p className="text-xs text-muted mt-0.5 mb-0">
                                    Matches if the user visits a matching URL at any point during the session. For more
                                    control, use a <strong>$pageview</strong> event trigger with property filters.
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={() => setIsAddingUrl(true)}
                            >
                                Add
                            </LemonButton>
                        </div>

                        {triggerGroup.urls.length > 0 && (
                            <div className="flex flex-wrap gap-2 mb-2">
                                {triggerGroup.urls.map((urlConfig) => (
                                    <LemonSnack key={urlConfig.url} onClose={() => removeUrl(urlConfig.url)}>
                                        {urlConfig.url}
                                    </LemonSnack>
                                ))}
                            </div>
                        )}

                        {isAddingUrl && (
                            <div className="border rounded p-3 bg-bg-3000 mb-2">
                                <LemonBanner type="info" className="text-sm mb-2">
                                    We always wrap the URL regex with anchors to avoid unexpected behavior (if you do
                                    not). This is because <code className="inline">https://example.com/</code> does not
                                    only match the homepage. You'd need{' '}
                                    <code className="inline">^https://example.com/$</code>
                                </LemonBanner>
                                <LemonLabel>Matching regex:</LemonLabel>
                                <div className="flex gap-2 mt-1">
                                    <LemonInput
                                        value={newUrl}
                                        onChange={setNewUrl}
                                        onPressEnter={() => addUrl(newUrl)}
                                        placeholder="e.g., /checkout/.*, ^https://example.com/page$"
                                        fullWidth
                                        autoFocus
                                    />
                                    <LemonButton type="secondary" onClick={() => setIsAddingUrl(false)}>
                                        Cancel
                                    </LemonButton>
                                    <LemonButton type="primary" onClick={() => addUrl(newUrl)}>
                                        Save
                                    </LemonButton>
                                </div>
                                {triggerGroup.urls.length > 0 && (
                                    <div className="mt-3 pt-3 border-t">
                                        <LemonLabel className="text-xs mb-1 block">
                                            Test a URL against existing patterns:
                                        </LemonLabel>
                                        <LemonInput
                                            value={testUrl}
                                            onChange={setTestUrl}
                                            placeholder="Enter a URL to test (e.g., https://example.com/page)"
                                            fullWidth
                                            size="small"
                                        />
                                        {testUrl && (
                                            <div className="text-xs mt-1">
                                                {triggerGroup.urls.some((urlConfig) => {
                                                    try {
                                                        const regex = new RegExp(urlConfig.url)
                                                        return regex.test(testUrl)
                                                    } catch {
                                                        return false
                                                    }
                                                }) ? (
                                                    <span className="text-success">Matches at least one pattern</span>
                                                ) : (
                                                    <span className="text-danger">Doesn't match any patterns</span>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Feature Flag */}
                    <div className="mb-4">
                        <div className="flex items-center gap-2 justify-between mb-2">
                            <LemonLabel>Feature flag</LemonLabel>
                            {!triggerGroup.flag && (
                                <FlagSelector value={undefined} onChange={addFlag} initialButtonLabel="Add flag" />
                            )}
                        </div>
                        {triggerGroup.flag && (
                            <div className="flex flex-wrap gap-2">
                                <LemonSnack onClose={removeFlag}>{triggerGroup.flag}</LemonSnack>
                            </div>
                        )}
                    </div>

                    {triggerGroup.events.length === 0 && triggerGroup.urls.length === 0 && !triggerGroup.flag && (
                        <p className="text-xs text-muted italic">
                            No conditions added yet. A trigger group will match all sessions if there are no conditions.
                        </p>
                    )}
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t">
                    <LemonButton type="secondary" onClick={onCancel} data-attr="trigger-group-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isTriggerGroupSubmitting}
                        disabledReason={!triggerGroup.name.trim() ? 'Group name is required' : undefined}
                        data-attr="trigger-group-save"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

interface DeleteLastGroupModalProps {
    isOpen: boolean
    onClose: () => void
    onConfirm: () => void
    groupName: string
}

function DeleteLastGroupModal({ isOpen, onClose, onConfirm, groupName }: DeleteLastGroupModalProps): JSX.Element {
    const { legacyTriggersPreview } = useValues(replayTriggersV2Logic)

    const { sampleRate, minDurationMs, matchType, urls, events, flag, hasConditions } = legacyTriggersPreview

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Delete last trigger group?">
            <div className="space-y-4">
                <p>
                    Deleting "{groupName}" will remove all trigger groups and your project will revert to using{' '}
                    <strong>legacy recording triggers</strong>.
                </p>

                <p className="text-sm text-muted">
                    Your project will immediately use the following legacy trigger configuration:
                </p>

                <div className="border rounded p-3 bg-surface-primary">
                    {hasConditions ? (
                        <>
                            <div className="mb-2">
                                <span className="text-sm">
                                    Match <b>sessions</b> against{' '}
                                    <LemonTag type="success" className="uppercase">
                                        {matchType}
                                    </LemonTag>{' '}
                                    criteria
                                </span>
                            </div>

                            {/* Conditions */}
                            <div className="space-y-2 text-sm mb-3">
                                {urls.length > 0 && (
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-muted">User has visited URL matching pattern</span>
                                        {urls.map((u) => (
                                            <LemonSnack key={u.url}>{u.url}</LemonSnack>
                                        ))}
                                    </div>
                                )}
                                {events.length > 0 && (
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-muted">Event</span>
                                        {events.map((event) => (
                                            <LemonSnack key={event}>{event}</LemonSnack>
                                        ))}
                                        <span className="text-muted">occurred</span>
                                    </div>
                                )}
                                {flag && (
                                    <div className="flex items-center gap-2 flex-wrap">
                                        <span className="text-muted">Feature flag</span>
                                        <LemonSnack>{typeof flag === 'string' ? flag : flag.key}</LemonSnack>
                                        <span className="text-muted">is enabled</span>
                                    </div>
                                )}
                            </div>
                        </>
                    ) : null}

                    {/* Sample rate - always shown */}
                    <div className="flex items-center gap-2 text-sm">
                        <span className="text-muted">Sample</span>
                        <span className="font-semibold">{Math.round(sampleRate * 100)}%</span>
                        <span className="text-muted">of all sessions</span>
                    </div>

                    {/* Minimum duration */}
                    {minDurationMs !== undefined && minDurationMs !== null && minDurationMs > 0 && (
                        <div className="text-sm text-muted mt-3">
                            Minimum duration: <b>{minDurationMs / 1000}</b> seconds
                        </div>
                    )}
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t">
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={onConfirm}
                        data-attr="trigger-group-delete-last-confirm"
                    >
                        Delete and use legacy trigger settings
                    </LemonButton>
                </div>
            </div>
        </LemonModal>
    )
}
