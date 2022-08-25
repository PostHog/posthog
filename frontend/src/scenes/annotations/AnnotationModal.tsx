import { LemonButton, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { DatePicker } from 'lib/components/DatePicker'
import React from 'react'
import { annotationScopeToName, annotationsPageLogic } from './annotationsPageLogic'
import { AnnotationScope } from '~/types'

export function AnnotationModal(): JSX.Element {
    const { isModalOpen, existingModalAnnotation, isAnnotationModalSubmitting } = useValues(annotationsPageLogic)
    const { closeModal, deleteAnnotation, submitAnnotationModal } = useActions(annotationsPageLogic)

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title={existingModalAnnotation ? 'Edit annotation' : 'New annotation'}
            description="Use annotations to add context to insights and dashboards."
            footer={
                <div className="flex-1 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        {existingModalAnnotation && (
                            <LemonButton
                                form="annotation-modal-form"
                                type="secondary"
                                status="danger"
                                onClick={() => {
                                    deleteAnnotation(existingModalAnnotation.id)
                                    closeModal()
                                }}
                            >
                                Delete annotation
                            </LemonButton>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <LemonButton form="annotation-modal-form" type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="annotation-modal-form"
                            htmlType="submit"
                            type="primary"
                            loading={isAnnotationModalSubmitting}
                        >
                            {existingModalAnnotation ? 'Edit' : 'Create'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={annotationsPageLogic}
                formKey="annotationModal"
                id="annotation-modal-form"
                enableFormOnSubmit
                className="space-y-4"
            >
                <div className="flex gap-2">
                    <Field name="dateMarker" label="Date and time" className="flex-1">
                        <DatePicker allowClear={false} showTime showSecond={false} />
                    </Field>
                    <Field name="scope" label="Scope" className="flex-1">
                        <LemonSelect
                            options={[
                                ...(existingModalAnnotation?.scope === AnnotationScope.Insight
                                    ? [
                                          {
                                              value: AnnotationScope.Insight,
                                              label: annotationScopeToName[AnnotationScope.Insight],
                                          },
                                      ]
                                    : []),
                                {
                                    value: AnnotationScope.Project,
                                    label: annotationScopeToName[AnnotationScope.Project],
                                },
                                {
                                    value: AnnotationScope.Organization,
                                    label: annotationScopeToName[AnnotationScope.Organization],
                                },
                            ]}
                            fullWidth
                        />
                    </Field>
                </div>
                <Field name="content" label="Content">
                    <LemonTextArea
                        placeholder="What's this annotation about?"
                        onPressCmdEnter={submitAnnotationModal}
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}
