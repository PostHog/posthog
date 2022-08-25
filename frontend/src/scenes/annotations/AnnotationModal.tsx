import { LemonButton, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { DatePicker } from 'lib/components/DatePicker'
import React from 'react'
import { annotationScopeToName, annotationsPageLogic } from './logic'
import { AnnotationScope } from '~/types'

export function AnnotationModal(): JSX.Element {
    const { isModalOpen, modalAnnotation } = useValues(annotationsPageLogic)
    const { closeModal } = useActions(annotationsPageLogic)

    const editingExistingAnnotation = !!modalAnnotation

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            title={modalAnnotation ? 'Edit annotation' : 'New annotation'}
            description="Use annotations to add context to insights and dashboards."
            footer={
                <>
                    {editingExistingAnnotation && (
                        <LemonButton form="annotation-modal-form" type="secondary" status="danger">
                            Delete
                        </LemonButton>
                    )}
                    <LemonButton form="annotation-modal-form" type="secondary">
                        Cancel
                    </LemonButton>
                    <LemonButton form="annotation-modal-form" htmlType="submit" type="primary">
                        Create
                    </LemonButton>
                </>
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
                        <DatePicker />
                    </Field>
                    <Field name="scope" label="Scope" className="flex-1">
                        <LemonSelect
                            options={[
                                ...(modalAnnotation?.scope === AnnotationScope.Insight
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
                    <LemonTextArea placeholder="What's this annotation about?" />
                </Field>
            </Form>
        </LemonModal>
    )
}
