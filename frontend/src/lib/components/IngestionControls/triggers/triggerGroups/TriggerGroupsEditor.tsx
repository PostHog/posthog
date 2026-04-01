import { useValues, useActions } from 'kea'
import { Form } from 'kea-forms'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { FlagSelector } from 'lib/components/FlagSelector'
import { EventTriggerSelect } from 'lib/components/IngestionControls/triggers/EventTrigger'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { TRIGGER_GROUPS_MIN_SDK_VERSION } from 'scenes/settings/environment/ReplayTriggers'
import { Since } from 'scenes/settings/environment/SessionRecordingSettings'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

import { replayTriggersV2Logic } from './replayTriggersV2Logic'
import { TriggerGroupCard } from './TriggerGroupCard'
import { triggerGroupFormLogic } from './triggerGroupFormLogic'

export function TriggerGroupsEditor(): JSX.Element {
    const { triggerGroups, isAddingGroup, editingGroupId } = useValues(replayTriggersV2Logic)
    const { addTriggerGroup, updateTriggerGroup, deleteTriggerGroup, setIsAddingGroup, setEditingGroupId } =
        useActions(replayTriggersV2Logic)

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
                    <LemonButton type="primary" icon={<IconPlus />} size="small" onClick={() => setIsAddingGroup(true)}>
                        Add
                    </LemonButton>
                )}
            </div>

            <p className="text-xs text-muted">
                Configure custom recording triggers with individual sampling rates per group. Recording will start if
                any of the recording trigger groups match.
            </p>

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
                                    onDelete={deleteTriggerGroup}
                                />
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

interface GroupFormProps {
    group?: SessionRecordingTriggerGroup
    onSave: (group: SessionRecordingTriggerGroup) => void
    onCancel: () => void
}

function GroupForm({ group, onSave, onCancel }: GroupFormProps): JSX.Element {
    const logic = triggerGroupFormLogic({ group, onSave, onCancel })
    const { triggerGroup, isAddingUrl, newUrl, testUrl, isTriggerGroupSubmitting } = useValues(logic)
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
    } = useActions(logic)

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
                                events={triggerGroup.events}
                                onChange={(events) => setTriggerGroupValue('events', events)}
                            />
                        </div>
                        {triggerGroup.events.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {triggerGroup.events.map((event) => (
                                    <LemonSnack key={event} onClose={() => removeEvent(event)}>
                                        {event}
                                    </LemonSnack>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* URLs */}
                    <div className="mb-4">
                        <div className="flex items-center gap-2 justify-between mb-2">
                            <LemonLabel>URL patterns (regex)</LemonLabel>
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
                            <>
                                <div className="border rounded p-3 bg-bg-3000 mb-2">
                                    <LemonLabel className="text-sm font-medium mb-2 block">
                                        Test a URL against these patterns:
                                    </LemonLabel>
                                    <LemonInput
                                        value={testUrl}
                                        onChange={setTestUrl}
                                        placeholder="Enter a URL to test (e.g., https://example.com/page)"
                                        fullWidth
                                    />
                                    {testUrl && (
                                        <div className="text-xs mt-2">
                                            {triggerGroup.urls.some((urlConfig) => {
                                                try {
                                                    const regex = new RegExp(urlConfig.url)
                                                    return regex.test(testUrl)
                                                } catch {
                                                    return false
                                                }
                                            }) ? (
                                                <span className="text-success">
                                                    ✓ This URL matches at least one pattern
                                                </span>
                                            ) : (
                                                <span className="text-danger">
                                                    ✗ This URL doesn't match any patterns
                                                </span>
                                            )}
                                        </div>
                                    )}
                                </div>
                                <div className="space-y-2">
                                    {triggerGroup.urls.map((urlConfig) => (
                                        <div key={urlConfig.url} className="border rounded flex items-center p-2 pl-4">
                                            <span className="flex-1 truncate">
                                                <span>Matches regex: </span>
                                                <span>{urlConfig.url}</span>
                                            </span>
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="small"
                                                status="danger"
                                                onClick={() => removeUrl(urlConfig.url)}
                                            >
                                                Remove
                                            </LemonButton>
                                        </div>
                                    ))}
                                </div>
                            </>
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
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isTriggerGroupSubmitting}
                        disabledReason={!triggerGroup.name.trim() ? 'Group name is required' : undefined}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}
