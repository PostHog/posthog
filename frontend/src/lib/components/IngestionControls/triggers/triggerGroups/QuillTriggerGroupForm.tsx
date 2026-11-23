import { useActions, useValues } from 'kea'
import { Form, Field as KeaField } from 'kea-forms'
import { useId } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Chip,
    ChipClose,
    Field,
    FieldError,
    FieldLabel,
    Heading,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Text,
} from '@posthog/quill'

import { FlagSelector } from 'lib/components/FlagSelector'
import { QuillEventTriggerSelect } from 'lib/components/IngestionControls/triggers/QuillEventTriggerSelect'
import { QuillMinDurationTrigger } from 'lib/components/IngestionControls/triggers/QuillMinDurationTrigger'
import { QuillUrlPatternHint } from 'lib/components/IngestionControls/triggers/QuillUrlPatternHint'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

import { QuillTriggerGroupEventRow } from './QuillTriggerGroupEventRow'
import { triggerGroupFormLogic } from './triggerGroupFormLogic'
import { urlMatchesAnyPattern, withAddedEvents } from './triggerGroupHelpers'

const MATCH_TYPE_OPTIONS: { value: 'any' | 'all'; label: string }[] = [
    { value: 'any', label: 'ANY condition matches' },
    { value: 'all', label: 'ALL conditions match' },
]

export function QuillTriggerGroupForm({
    group,
    onSave,
    onCancel,
}: {
    group?: SessionRecordingTriggerGroup
    onSave: (group: SessionRecordingTriggerGroup) => void
    onCancel: () => void
}): JSX.Element {
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
    const newUrlId = useId()
    const testUrlId = useId()

    const handleAddEvent = (events: string[]): void => {
        setTriggerGroupValue('events', withAddedEvents(triggerGroup.events, events))
    }

    return (
        <Form
            logic={triggerGroupFormLogic}
            props={{ group, onSave, onCancel }}
            formKey="triggerGroup"
            enableFormOnSubmit
            className="flex flex-col gap-4 rounded-md border border-border p-4"
        >
            <KeaField name="name" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>Group name</FieldLabel>
                        <Input
                            id={id}
                            value={value ?? ''}
                            onChange={(event) => onChange(event.target.value)}
                            placeholder="e.g., Error Tracking, Feature Testing"
                        />
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>

            <div className="flex flex-wrap gap-4">
                <KeaField name="sampleRate" noStyle>
                    {({ id, value, onChange, error }) => (
                        <Field data-invalid={error ? true : undefined} className="min-w-40 flex-1">
                            <FieldLabel htmlFor={id}>Sample rate (%)</FieldLabel>
                            <Input
                                id={id}
                                type="number"
                                min={0}
                                max={100}
                                value={value ?? ''}
                                onChange={(event) =>
                                    onChange(event.target.value === '' ? undefined : Number(event.target.value))
                                }
                            />
                            {error && <FieldError>{error}</FieldError>}
                        </Field>
                    )}
                </KeaField>

                <KeaField name="minDurationMs" noStyle>
                    {({ value, onChange, error }) => (
                        <Field data-invalid={error ? true : undefined} className="min-w-40 flex-1">
                            <Label>Minimum duration (seconds)</Label>
                            <QuillMinDurationTrigger value={value} onChange={onChange} />
                            {error && <FieldError>{error}</FieldError>}
                        </Field>
                    )}
                </KeaField>
            </div>

            <KeaField name="matchType" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>Match type</FieldLabel>
                        <Select value={value} onValueChange={(next) => next && onChange(next)}>
                            <SelectTrigger id={id}>
                                <SelectValue>
                                    {(selected: 'any' | 'all') =>
                                        MATCH_TYPE_OPTIONS.find((option) => option.value === selected)?.label
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {MATCH_TYPE_OPTIONS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>

            <Separator />

            <div className="flex flex-col gap-4">
                <Heading size="sm" render={<h4 className="m-0" />}>
                    Conditions
                </Heading>

                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Label>Event triggers</Label>
                        <QuillEventTriggerSelect
                            events={triggerGroup.events.map((e) => e.name)}
                            onChange={handleAddEvent}
                        />
                    </div>
                    {triggerGroup.events.map((event) => (
                        <QuillTriggerGroupEventRow
                            key={event.name}
                            event={event}
                            isExpanded={expandedEvent === event.name}
                            onToggle={() => setExpandedEvent(expandedEvent === event.name ? null : event.name)}
                            onRemove={() => removeEvent(event.name)}
                            onUpdateProperties={(properties) => setEventProperties(event.name, properties)}
                        />
                    ))}
                </div>

                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <Label>URL patterns (regex)</Label>
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Matches if the user visits a matching URL at any point during the session. For more
                                control, use a <strong>$pageview</strong> event trigger with property filters.
                            </Text>
                        </div>
                        <Button variant="outline" onClick={() => setIsAddingUrl(true)}>
                            <IconPlus />
                            Add
                        </Button>
                    </div>

                    {triggerGroup.urls.length > 0 && (
                        <div className="flex flex-wrap gap-2">
                            {triggerGroup.urls.map((urlConfig) => (
                                <Chip key={urlConfig.url}>
                                    {urlConfig.url}
                                    <ChipClose
                                        aria-label={`Remove ${urlConfig.url}`}
                                        onClick={() => removeUrl(urlConfig.url)}
                                    />
                                </Chip>
                            ))}
                        </div>
                    )}

                    {isAddingUrl && (
                        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
                            <QuillUrlPatternHint />
                            <Field>
                                <FieldLabel htmlFor={newUrlId}>Matching regex:</FieldLabel>
                                <div className="flex flex-wrap gap-2">
                                    <Input
                                        id={newUrlId}
                                        className="min-w-60 flex-1"
                                        value={newUrl}
                                        onChange={(event) => setNewUrl(event.target.value)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter') {
                                                event.preventDefault()
                                                addUrl(newUrl)
                                            }
                                        }}
                                        placeholder="e.g., https://example.com/checkout.*, ^https://example.com/page$"
                                        autoFocus
                                    />
                                    <Button variant="outline" onClick={() => setIsAddingUrl(false)}>
                                        Cancel
                                    </Button>
                                    <Button variant="primary" onClick={() => addUrl(newUrl)}>
                                        Add
                                    </Button>
                                </div>
                            </Field>
                            {triggerGroup.urls.length > 0 && (
                                <>
                                    <Separator />
                                    <Field>
                                        <FieldLabel htmlFor={testUrlId}>
                                            Test a full URL against existing patterns:
                                        </FieldLabel>
                                        <Input
                                            id={testUrlId}
                                            value={testUrl}
                                            onChange={(event) => setTestUrl(event.target.value)}
                                            placeholder="e.g., https://example.com/checkout?step=2"
                                        />
                                        {testUrl &&
                                            (urlMatchesAnyPattern(triggerGroup.urls, testUrl) ? (
                                                <Text
                                                    size="xs"
                                                    className="text-success-foreground"
                                                    render={<p className="m-0" />}
                                                >
                                                    Matches at least one pattern
                                                </Text>
                                            ) : (
                                                <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                                                    Doesn't match any patterns. Patterns match the full URL, so a path
                                                    on its own never matches.
                                                </Text>
                                            ))}
                                    </Field>
                                </>
                            )}
                        </div>
                    )}
                </div>

                <div className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Label>Feature flag</Label>
                        {!triggerGroup.flag && (
                            <FlagSelector value={undefined} onChange={addFlag} initialButtonLabel="Add flag" />
                        )}
                    </div>
                    {triggerGroup.flag && (
                        <div className="flex flex-wrap gap-2">
                            <Chip>
                                {triggerGroup.flag}
                                <ChipClose aria-label={`Remove ${triggerGroup.flag}`} onClick={removeFlag} />
                            </Chip>
                        </div>
                    )}
                </div>

                {triggerGroup.events.length === 0 && triggerGroup.urls.length === 0 && !triggerGroup.flag && (
                    <Text size="xs" variant="muted" render={<p className="m-0 italic" />}>
                        No conditions added yet. A trigger group will match all sessions if there are no conditions.
                    </Text>
                )}
            </div>

            <Separator />

            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={onCancel} data-attr="trigger-group-cancel">
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    type="submit"
                    loading={isTriggerGroupSubmitting}
                    disabledReason={!triggerGroup.name.trim() ? 'Group name is required' : undefined}
                    data-attr="trigger-group-save"
                >
                    Save
                </Button>
            </div>
        </Form>
    )
}
