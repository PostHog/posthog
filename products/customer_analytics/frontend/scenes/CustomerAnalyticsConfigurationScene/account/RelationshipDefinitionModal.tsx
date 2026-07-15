import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { relationshipDefinitionsLogic } from './relationshipDefinitionsLogic'

export function RelationshipDefinitionModal(): JSX.Element {
    const { modalVisible, editingDefinition, isRelationshipDefinitionFormSubmitting } =
        useValues(relationshipDefinitionsLogic)
    const { closeModal, submitRelationshipDefinitionForm } = useActions(relationshipDefinitionsLogic)

    return (
        <LemonModal
            isOpen={modalVisible}
            onClose={closeModal}
            title={editingDefinition ? 'Edit relationship' : 'New relationship'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRelationshipDefinitionForm}
                        loading={isRelationshipDefinitionFormSubmitting}
                    >
                        {editingDefinition ? 'Save' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={relationshipDefinitionsLogic}
                formKey="relationshipDefinitionForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g. Onboarding manager" autoFocus fullWidth />
                </LemonField>
                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea
                        placeholder="What this relationship means, e.g. 'Runs onboarding for this account'"
                        minRows={2}
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
