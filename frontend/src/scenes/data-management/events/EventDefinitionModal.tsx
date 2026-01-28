import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { UserBasicType } from '~/types'

import { eventDefinitionModalLogic } from './eventDefinitionModalLogic'

export interface EventDefinitionModalProps {
    isOpen: boolean
    onClose: () => void
}

export function EventDefinitionModal({ isOpen, onClose }: EventDefinitionModalProps): JSX.Element {
    const logic = eventDefinitionModalLogic({ onClose })
    const { eventDefinitionForm, isEventDefinitionFormSubmitting, existingEvent } = useValues(logic)
    const { setEventDefinitionFormValue: setFormValue, submitEventDefinitionForm } = useActions(logic)
    const { tags } = useValues(tagsModel)

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
                        disabled={!eventDefinitionForm.name || !!existingEvent}
                    >
                        Create event
                    </LemonButton>
                </>
            }
        >
            <Form logic={eventDefinitionModalLogic} formKey="eventDefinitionForm" className="space-y-4">
                <LemonBanner type="info">
                    <strong>Note:</strong> Event names cannot be changed after creation. Choose your name carefully.
                </LemonBanner>

                {existingEvent && (
                    <LemonBanner type="warning">
                        An event with the name "{existingEvent.name}" already exists.{' '}
                        <Link to={urls.eventDefinition(existingEvent.id)}>View existing event</Link>
                    </LemonBanner>
                )}

                <LemonField name="name" label="Event name">
                    <LemonInput
                        value={eventDefinitionForm.name}
                        onChange={(value) => setFormValue('name', value)}
                        placeholder="e.g., user_signed_up"
                        autoFocus
                        data-attr="event-definition-name-input"
                    />
                </LemonField>

                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea
                        value={eventDefinitionForm.description}
                        onChange={(value) => setFormValue('description', value)}
                        placeholder="What does this event represent?"
                        data-attr="event-definition-description-input"
                    />
                </LemonField>

                <div className="flex items-center gap-4">
                    <LemonField name="owner" label="Owner" showOptional className="w-60">
                        <MemberSelect
                            value={eventDefinitionForm.owner ?? null}
                            onChange={(user: UserBasicType | null) => setFormValue('owner', user?.id ?? null)}
                            data-attr="event-definition-owner-select"
                        />
                    </LemonField>

                    <LemonField name="tags" label="Tags" showOptional className="flex-1">
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={eventDefinitionForm.tags || []}
                            options={tags.map((tag) => ({ key: tag, label: tag }))}
                            onChange={(tags) => setFormValue('tags', tags)}
                            placeholder="Add tags..."
                            data-attr="event-definition-tags-input"
                        />
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
