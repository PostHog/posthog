import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { customPropertyDefinitionsLogic } from './customPropertyDefinitionsLogic'
import { DISPLAY_TYPE_OPTIONS, isNumericDisplayType } from './customPropertyTypes'

export function CustomPropertyModal(): JSX.Element {
    const { modalVisible, editingDefinition, customPropertyForm, isCustomPropertyFormSubmitting } =
        useValues(customPropertyDefinitionsLogic)
    const { closeModal, submitCustomPropertyForm } = useActions(customPropertyDefinitionsLogic)

    const showBigNumberSwitch = isNumericDisplayType(customPropertyForm.displayType)

    return (
        <LemonModal
            isOpen={modalVisible}
            onClose={closeModal}
            title={editingDefinition ? 'Edit custom property' : 'New custom property'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitCustomPropertyForm}
                        loading={isCustomPropertyFormSubmitting}
                    >
                        {editingDefinition ? 'Save' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={customPropertyDefinitionsLogic}
                formKey="customPropertyForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g. ARR" autoFocus />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea placeholder="Optional description" minRows={2} />
                </LemonField>
                <LemonField name="displayType" label="Type">
                    <LemonSelect options={DISPLAY_TYPE_OPTIONS} fullWidth />
                </LemonField>
                {showBigNumberSwitch && (
                    <LemonField name="isBigNumber">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Abbreviate large numbers (e.g. 10,000 → 10K)"
                                bordered
                            />
                        )}
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}
