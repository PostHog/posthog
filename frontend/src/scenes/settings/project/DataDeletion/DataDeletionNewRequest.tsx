import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect, Link } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { dataDeletionLogic } from './dataDeletionLogic'
import { DataDeletionPreviewPanel } from './DataDeletionPreviewPanel'

export function DataDeletionNewRequest(): JSX.Element {
    const {
        newRequest,
        isNewRequestSubmitting,
        newRequestHasErrors,
        preview,
        previewLoading,
        previewScoped,
        previewIsFresh,
    } = useValues(dataDeletionLogic)
    const { setNewRequestValue, submitNewRequest, runPreview } = useActions(dataDeletionLogic)
    const [confirmText, setConfirmText] = useState('')
    const [confirmOpen, setConfirmOpen] = useState(false)

    const isPropertyRemoval = newRequest.request_type === 'property_removal'

    return (
        <div className="flex flex-col gap-4">
            <LemonBanner type="warning">
                <div className="flex flex-col gap-1">
                    <b>Deletions are permanent and irreversible.</b>
                    <span>
                        Your request will be reviewed by PostHog before execution, typically within one business day.
                        Narrow the time range and use predicates to limit the scope.
                    </span>
                </div>
            </LemonBanner>

            <Form logic={dataDeletionLogic} formKey="newRequest" className="flex flex-col gap-4">
                <LemonField name="request_type" label="I want to delete">
                    <LemonSelect
                        className="w-fit"
                        dropdownMatchSelectWidth={false}
                        options={[
                            { value: 'event_removal', label: 'Events' },
                            { value: 'property_removal', label: 'Properties from events' },
                        ]}
                        value={newRequest.request_type}
                        onChange={(value) => setNewRequestValue('request_type', value)}
                    />
                </LemonField>

                <LemonField.Pure label="Between">
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonField name="start_time" inline>
                                <LemonCalendarSelectInput
                                    value={newRequest.start_time ? dayjs(newRequest.start_time) : null}
                                    onChange={(date) =>
                                        setNewRequestValue('start_time', date ? date.toISOString() : null)
                                    }
                                    placeholder="start date"
                                    granularity="minute"
                                />
                            </LemonField>
                            <span className="text-secondary">and</span>
                            {newRequest.end_time_through_now ? (
                                <span className="text-secondary italic">now (resolved when you preview)</span>
                            ) : (
                                <LemonField name="end_time" inline>
                                    <LemonCalendarSelectInput
                                        value={newRequest.end_time ? dayjs(newRequest.end_time) : null}
                                        onChange={(date) =>
                                            setNewRequestValue('end_time', date ? date.toISOString() : null)
                                        }
                                        placeholder="end date"
                                        granularity="minute"
                                    />
                                </LemonField>
                            )}
                        </div>
                        <LemonSwitch
                            label='end at "now" (resolved at submission)'
                            checked={newRequest.end_time_through_now}
                            onChange={(checked) => {
                                setNewRequestValue('end_time_through_now', checked)
                                if (checked) {
                                    setNewRequestValue('end_time', null)
                                }
                            }}
                        />
                    </div>
                </LemonField.Pure>

                {!isPropertyRemoval && (
                    <LemonField.Pure label="more specifically, delete">
                        <div className="flex flex-col gap-2">
                            {!newRequest.delete_all_events && (
                                <div className="flex flex-wrap items-center gap-2">
                                    <TaxonomicPopover
                                        groupType={TaxonomicFilterGroupType.Events}
                                        value={null}
                                        onChange={(value) => {
                                            if (!value || newRequest.events.includes(String(value))) {
                                                return
                                            }
                                            setNewRequestValue('events', [...newRequest.events, String(value)])
                                        }}
                                        placeholder={
                                            newRequest.events.length === 0 ? 'these events' : 'or another event'
                                        }
                                        type="secondary"
                                    />
                                    {newRequest.events.map((name) => (
                                        <LemonButton
                                            key={name}
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() =>
                                                setNewRequestValue(
                                                    'events',
                                                    newRequest.events.filter((e) => e !== name)
                                                )
                                            }
                                        >
                                            {name} ×
                                        </LemonButton>
                                    ))}
                                </div>
                            )}
                            <LemonSwitch
                                label="all events in the time range"
                                checked={newRequest.delete_all_events}
                                onChange={(checked) => {
                                    setNewRequestValue('delete_all_events', checked)
                                    if (checked) {
                                        setNewRequestValue('events', [])
                                    }
                                }}
                            />
                        </div>
                    </LemonField.Pure>
                )}

                {isPropertyRemoval && (
                    <LemonField.Pure label="Properties to remove">
                        <div className="flex flex-wrap items-center gap-2">
                            <TaxonomicPopover
                                groupType={TaxonomicFilterGroupType.EventProperties}
                                value={null}
                                onChange={(value) => {
                                    if (!value || newRequest.properties.includes(String(value))) {
                                        return
                                    }
                                    setNewRequestValue('properties', [...newRequest.properties, String(value)])
                                }}
                                placeholder={
                                    newRequest.properties.length === 0 ? 'Pick properties' : 'Add another property'
                                }
                                type="secondary"
                            />
                            {newRequest.properties.map((name) => (
                                <LemonButton
                                    key={name}
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() =>
                                        setNewRequestValue(
                                            'properties',
                                            newRequest.properties.filter((p) => p !== name)
                                        )
                                    }
                                >
                                    {name} ×
                                </LemonButton>
                            ))}
                        </div>
                    </LemonField.Pure>
                )}

                <LemonField
                    name="hogql_predicate"
                    label="and optionally, match this SQL expression"
                    showOptional
                    info={
                        <div className="flex flex-col gap-1">
                            <span>Returns a boolean that further narrows which events are matched. For example:</span>
                            <code className="text-xs">properties.$browser = 'Chrome'</code>
                            <code className="text-xs">distinct_id IN ('user-1', 'user-2')</code>
                        </div>
                    }
                    help={
                        <span>
                            Further narrows which events are matched.{' '}
                            <Link to="https://posthog.com/docs/sql" target="_blank">
                                Learn more about SQL
                            </Link>
                        </span>
                    }
                >
                    <CodeEditorInline
                        value={newRequest.hogql_predicate}
                        onChange={(value) => setNewRequestValue('hogql_predicate', value ?? '')}
                        language="hogQLExpr"
                        minHeight="60px"
                    />
                </LemonField>

                <LemonField name="notes" label="Notes for PostHog reviewers" showOptional>
                    <LemonTextArea
                        value={newRequest.notes}
                        onChange={(value) => setNewRequestValue('notes', value)}
                        placeholder="Context that will help us review your request"
                        minRows={2}
                        maxRows={10}
                    />
                </LemonField>
            </Form>

            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-secondary text-sm">
                    Preview the matched events before submitting. Re-run the preview after any change.
                </span>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => runPreview()}
                        loading={previewLoading}
                        disabledReason={
                            !previewScoped
                                ? 'Fill in the scope first'
                                : previewIsFresh
                                  ? 'Preview is up to date'
                                  : undefined
                        }
                    >
                        {preview ? 'Re-run preview' : 'Preview events'}
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        disabledReason={
                            newRequestHasErrors
                                ? 'Fix the form errors first'
                                : !previewIsFresh
                                  ? 'Run a preview that matches the current settings before submitting'
                                  : preview && preview.count === 0
                                    ? 'Preview matches 0 events — nothing to delete'
                                    : undefined
                        }
                        onClick={() => setConfirmOpen(true)}
                        loading={isNewRequestSubmitting}
                    >
                        Submit deletion request
                    </LemonButton>
                </div>
            </div>

            <DataDeletionPreviewPanel />

            <LemonModal
                title="Confirm deletion request"
                isOpen={confirmOpen}
                onClose={() => setConfirmOpen(false)}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setConfirmOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            status="danger"
                            type="primary"
                            disabled={confirmText.toLowerCase() !== 'delete'}
                            loading={isNewRequestSubmitting}
                            onClick={() => {
                                setConfirmOpen(false)
                                setConfirmText('')
                                submitNewRequest()
                            }}
                        >
                            Submit for review
                        </LemonButton>
                    </>
                }
            >
                <p>
                    This request covers approximately <b>{preview?.count ?? 0}</b> events. Once approved by PostHog,
                    deletion is <b>permanent</b>. Type <b>delete</b> to confirm.
                </p>
                <LemonInput value={confirmText} onChange={setConfirmText} placeholder="delete" />
            </LemonModal>
        </div>
    )
}
