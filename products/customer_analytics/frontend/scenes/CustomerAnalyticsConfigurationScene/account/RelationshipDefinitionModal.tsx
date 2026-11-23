import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Textarea,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { relationshipDefinitionsLogic } from './relationshipDefinitionsLogic'

export function RelationshipDefinitionModal(): JSX.Element {
    const { modalVisible, editingDefinition, isRelationshipDefinitionFormSubmitting } =
        useValues(relationshipDefinitionsLogic)
    const { closeModal, submitRelationshipDefinitionForm } = useActions(relationshipDefinitionsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Dialog
                open={modalVisible}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        closeModal()
                    }
                }}
            >
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{editingDefinition ? 'Edit relationship' : 'New relationship'}</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <Form
                            logic={relationshipDefinitionsLogic}
                            formKey="relationshipDefinitionForm"
                            enableFormOnSubmit
                            className="flex flex-col gap-4"
                        >
                            <QuillSettingFormField name="name" label="Name">
                                {({ id, value, onChange, invalid }) => (
                                    <Input
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="e.g. Onboarding manager"
                                        autoFocus
                                        aria-invalid={invalid || undefined}
                                    />
                                )}
                            </QuillSettingFormField>
                            <QuillSettingFormField name="description" label="Description (optional)">
                                {({ id, value, onChange, invalid }) => (
                                    <Textarea
                                        id={id}
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="What this relationship means, e.g. 'Runs onboarding for this account'"
                                        rows={2}
                                        aria-invalid={invalid || undefined}
                                    />
                                )}
                            </QuillSettingFormField>
                        </Form>
                    </DialogBody>
                    <DialogFooter>
                        <Button variant="outline" onClick={closeModal}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            onClick={submitRelationshipDefinitionForm}
                            loading={isRelationshipDefinitionFormSubmitting}
                        >
                            {editingDefinition ? 'Save' : 'Create'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        )
    }

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
