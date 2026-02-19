import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { HogFunctionUserTemplateLogicProps, hogFunctionUserTemplateLogic } from './hogFunctionUserTemplateLogic'

export function SaveAsHogFunctionTemplateModal(props: HogFunctionUserTemplateLogicProps): JSX.Element {
    const logic = hogFunctionUserTemplateLogic(props)
    const { saveAsTemplateModalVisible, isTemplateFormSubmitting, templateForm, isEditMode } = useValues(logic)
    const { hideSaveAsTemplateModal, submitTemplateForm } = useActions(logic)

    return (
        <LemonModal
            onClose={hideSaveAsTemplateModal}
            isOpen={saveAsTemplateModalVisible}
            title={isEditMode ? 'Update template' : 'Save as template'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={hideSaveAsTemplateModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitTemplateForm}
                        loading={isTemplateFormSubmitting}
                        disabledReason={!templateForm.name ? 'Name is required' : undefined}
                    >
                        {isEditMode ? 'Update template' : 'Save template'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={hogFunctionUserTemplateLogic} props={props} formKey="templateForm">
                <div className="space-y-4">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Template name" autoFocus />
                    </LemonField>

                    <LemonField name="description" label="Description (optional)">
                        <LemonTextArea placeholder="Template description" rows={3} />
                    </LemonField>

                    <LemonField name="tags" label="Tags (optional)">
                        <LemonInputSelect
                            mode="multiple"
                            value={templateForm.tags}
                            onChange={(tags) => {
                                hogFunctionUserTemplateLogic(props).actions.setTemplateFormValue('tags', tags)
                            }}
                            options={[]}
                            allowCustomValues={true}
                            placeholder="Type to add tags"
                        />
                    </LemonField>

                    <LemonField name="scope" label="Scope">
                        <LemonSelect
                            value={templateForm.scope}
                            options={[
                                { value: 'team', label: 'This project only' },
                                { value: 'organization', label: 'All projects in organization' },
                            ]}
                        />
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
