import { IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, LemonModalProps, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { DatePicker } from 'lib/components/DatePicker'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { shortTimeZone } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AnnotationScope } from '~/types'

import { ANNOTATION_DAYJS_FORMAT, annotationModalLogic, annotationScopeToName } from './annotationModalLogic'

export function NewAnnotationButton(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)
    return (
        <LemonButton type="primary" data-attr="create-annotation" onClick={() => openModalToCreateAnnotation()}>
            New annotation
        </LemonButton>
    )
}

export function AnnotationModal({
    overlayRef,
    contentRef,
}: Pick<LemonModalProps, 'overlayRef' | 'contentRef'>): JSX.Element {
    const { isModalOpen, existingModalAnnotation, isAnnotationModalSubmitting, onSavedInsight, timezone } =
        useValues(annotationModalLogic)
    const { closeModal, deleteAnnotation, submitAnnotationModal } = useActions(annotationModalLogic)

    const isInsightScoped = existingModalAnnotation?.scope === AnnotationScope.Insight

    return (
        <LemonModal
            overlayRef={overlayRef}
            contentRef={contentRef}
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
                                    deleteAnnotation(existingModalAnnotation)
                                    closeModal()
                                }}
                                data-attr="delete-annotation"
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
                            data-attr="create-annotation-submit"
                        >
                            {existingModalAnnotation ? 'Edit' : 'Create'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <Form
                logic={annotationModalLogic}
                formKey="annotationModal"
                id="annotation-modal-form"
                enableFormOnSubmit
                className="space-y-4"
            >
                <div className="flex gap-2">
                    <LemonField
                        name="dateMarker"
                        label={
                            <span>
                                Date and time (
                                <Link to={urls.settings('project', 'date-and-time')} target="_blank">
                                    {shortTimeZone(timezone)}
                                </Link>
                                )
                            </span>
                        }
                        className="flex-1"
                    >
                        <DatePicker
                            className="h-10"
                            allowClear={false}
                            showTime
                            showSecond={false}
                            format={ANNOTATION_DAYJS_FORMAT}
                        />
                    </LemonField>
                    <LemonField name="scope" label="Scope" className="flex-1">
                        <LemonSelect
                            options={[
                                ...(existingModalAnnotation?.scope === AnnotationScope.Insight || onSavedInsight
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
                                    sideIcon: isInsightScoped ? <IconWarning /> : undefined,
                                    tooltip: isInsightScoped
                                        ? "After saving, it won't be possible to make the annotation insight-scoped again."
                                        : undefined,
                                },
                                {
                                    value: AnnotationScope.Organization,
                                    label: annotationScopeToName[AnnotationScope.Organization],
                                    sideIcon: isInsightScoped ? <IconWarning /> : undefined,
                                    tooltip: isInsightScoped
                                        ? "After saving, it won't be possible to make the annotation insight-scoped again."
                                        : undefined,
                                },
                            ]}
                            fullWidth
                        />
                    </LemonField>
                </div>
                <LemonField name="content" label="Content">
                    <LemonTextArea
                        placeholder="What's this annotation about?"
                        onPressCmdEnter={submitAnnotationModal}
                        data-attr="create-annotation-input"
                        maxLength={400}
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
