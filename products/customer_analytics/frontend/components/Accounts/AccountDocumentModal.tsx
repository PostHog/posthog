import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { DOCUMENT_SOURCE_OPTIONS, DOCUMENT_STATUS_OPTIONS, DOCUMENT_TYPE_OPTIONS } from './accountDocumentLabels'
import { accountDocumentsLogic, AccountDocumentsLogicProps } from './accountDocumentsLogic'

export function AccountDocumentModal({ accountId, instanceId }: AccountDocumentsLogicProps): JSX.Element {
    const logic = accountDocumentsLogic({ accountId, instanceId })
    const { editorOpen, editingDocument, documentForm, isDocumentFormSubmitting } = useValues(logic)
    const { closeEditor, submitDocumentForm } = useActions(logic)
    const isPandaDoc = documentForm.source === 'pandadoc'

    return (
        <LemonModal
            isOpen={editorOpen}
            onClose={closeEditor}
            title={editingDocument ? 'Edit document' : 'Add document'}
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeEditor}
                        disabledReason={isDocumentFormSubmitting ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitDocumentForm}
                        loading={isDocumentFormSubmitting}
                        data-attr="account-document-save"
                    >
                        {editingDocument ? 'Save changes' : 'Add document'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={accountDocumentsLogic}
                props={{ accountId, instanceId }}
                formKey="documentForm"
                className="flex flex-col gap-4 @container"
            >
                <LemonField name="source" label="Source">
                    <LemonSelect options={DOCUMENT_SOURCE_OPTIONS} fullWidth />
                </LemonField>
                <LemonField
                    name="url"
                    label={isPandaDoc ? 'PandaDoc document' : 'Link'}
                    help={
                        isPandaDoc
                            ? 'Paste the document link from the PandaDoc editor. The name and status are read from PandaDoc.'
                            : undefined
                    }
                >
                    <LemonInput
                        placeholder={
                            isPandaDoc
                                ? 'https://app.pandadoc.com/a/#/documents/...'
                                : 'https://docs.example.com/quote.pdf'
                        }
                        fullWidth
                        autoFocus
                    />
                </LemonField>
                <LemonField name="title" label="Title" showOptional={isPandaDoc}>
                    <LemonInput
                        placeholder={isPandaDoc ? 'Defaults to the PandaDoc document name' : ''}
                        maxLength={512}
                        fullWidth
                    />
                </LemonField>
                <div className="grid grid-cols-1 @md:grid-cols-2 gap-3">
                    <LemonField name="document_type" label="Type">
                        <LemonSelect options={DOCUMENT_TYPE_OPTIONS} fullWidth />
                    </LemonField>
                    <LemonField
                        name="status"
                        label="Status"
                        help={isPandaDoc ? 'Replaced by the PandaDoc status on the next refresh.' : undefined}
                    >
                        <LemonSelect options={DOCUMENT_STATUS_OPTIONS} fullWidth />
                    </LemonField>
                    <LemonField name="effective_date" label="Effective date" showOptional>
                        {({ value, onChange }) => (
                            <LemonCalendarSelectInput
                                value={value ? dayjs(value) : null}
                                onChange={(date) => onChange(date?.format('YYYY-MM-DD') ?? null)}
                                granularity="day"
                                clearable
                                placeholder="Select a date"
                            />
                        )}
                    </LemonField>
                    <LemonField name="end_date" label="End date" showOptional>
                        {({ value, onChange }) => (
                            <LemonCalendarSelectInput
                                value={value ? dayjs(value) : null}
                                onChange={(date) => onChange(date?.format('YYYY-MM-DD') ?? null)}
                                granularity="day"
                                clearable
                                placeholder="Select a date"
                            />
                        )}
                    </LemonField>
                </div>
                <LemonField
                    name="amount"
                    label="Amount"
                    showOptional
                    help="Contract or quote value, in your team's currency."
                >
                    <LemonInput placeholder="0.00" fullWidth />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
