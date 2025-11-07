import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, UserBasicType } from '~/types'

import { eventDefinitionModalLogic } from './eventDefinitionModalLogic'

export interface EventDefinitionModalProps {
    isOpen: boolean
    onClose: () => void
    onSuccess?: () => void
}

export function EventDefinitionModal({ isOpen, onClose, onSuccess }: EventDefinitionModalProps): JSX.Element {
    const logic = eventDefinitionModalLogic({ onSuccess, onClose })
    const { eventDefinitionForm, isEventDefinitionFormSubmitting } = useValues(logic)
    const { setEventDefinitionFormValue: setFormValue, submitEventDefinitionForm } = useActions(logic)
    const { hasAvailableFeature } = useValues(userLogic)

    const hasIngestionTaxonomy = hasAvailableFeature(AvailableFeature.INGESTION_TAXONOMY)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Create event"
            description="Create a new event definition before any events are captured. First seen and last seen will be set when the first event is ingested."
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitEventDefinitionForm}
                        loading={isEventDefinitionFormSubmitting}
                    >
                        Create event
                    </LemonButton>
                </>
            }
        >
            <Form logic={eventDefinitionModalLogic} formKey="eventDefinitionForm" className="space-y-4">
                <LemonField name="name" label="Event name">
                    <LemonInput
                        value={eventDefinitionForm.name}
                        onChange={(value) => setFormValue('name', value)}
                        placeholder="e.g., user_signed_up"
                        autoFocus
                        data-attr="event-definition-name-input"
                    />
                </LemonField>

                {hasIngestionTaxonomy && (
                    <>
                        <LemonField name="description" label="Description" showOptional>
                            <LemonTextArea
                                value={eventDefinitionForm.description}
                                onChange={(value) => setFormValue('description', value)}
                                placeholder="What does this event represent?"
                                data-attr="event-definition-description-input"
                            />
                        </LemonField>

                        <LemonField name="owner" label="Owner" showOptional>
                            <MemberSelect
                                value={eventDefinitionForm.owner ?? null}
                                onChange={(user: UserBasicType | null) => setFormValue('owner', user?.id ?? null)}
                                data-attr="event-definition-owner-select"
                            />
                        </LemonField>
                    </>
                )}

                <LemonField name="tags" label="Tags" showOptional>
                    <ObjectTags
                        tags={eventDefinitionForm.tags || []}
                        onChange={(tags) => setFormValue('tags', tags)}
                        saving={false}
                        className="mb-2"
                        data-attr="event-definition-tags-input"
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
