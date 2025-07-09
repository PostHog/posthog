import {
    LemonButton,
    LemonCalendarSelectInput,
    LemonModal,
    LemonModalProps,
    LemonSelect,
    LemonSelectOptions,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { shortTimeZone } from 'lib/utils'
import { urls } from 'scenes/urls'

import { AnnotationScope, AnnotationType } from '~/types'

import { annotationModalLogic, annotationScopeToName } from './annotationModalLogic'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'

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
    const {
        isModalOpen,
        existingModalAnnotation,
        annotationModal,
        isAnnotationModalSubmitting,
        onSavedInsight,
        timezone,
    } = useValues(annotationModalLogic)
    const { closeModal, deleteAnnotation, submitAnnotationModal } = useActions(annotationModalLogic)

    const scopeOptions: LemonSelectOptions<AnnotationType['scope'] | null> = [
        {
            value: AnnotationScope.Insight,
            label: annotationScopeToName[AnnotationScope.Insight],
            tooltip: existingModalAnnotation?.insight_name ? (
                existingModalAnnotation.insight_name
            ) : existingModalAnnotation?.insight_derived_name ? (
                <i>{existingModalAnnotation.insight_derived_name}</i>
            ) : undefined,
            disabledReason:
                (!onSavedInsight && 'You need to save the insight first.') ||
                // if existing annotation data in db (for backwards compatibility) doesn't have insight id set on it
                // we can't let them change scope to insight as we don't know which insight to map to
                (existingModalAnnotation
                    ? !existingModalAnnotation?.dashboard_item &&
                      'To select this scope, open this annotation on the target insight'
                    : undefined),
            sideIcon: existingModalAnnotation?.insight_short_id ? (
                <Link
                    to={urls.insightView(existingModalAnnotation?.insight_short_id)}
                    target="_blank"
                    targetBlankIcon
                />
            ) : null,
        },
        {
            value: AnnotationScope.Dashboard,
            label: annotationScopeToName[AnnotationScope.Dashboard],
            tooltip: existingModalAnnotation?.dashboard_name,
            disabledReason:
                (!annotationModal.dashboardId &&
                    'To select this scope, open this annotation on the target dashboard') ||
                (existingModalAnnotation?.scope === AnnotationScope.Dashboard && 'Already scoped to dashboard') ||
                (existingModalAnnotation && existingModalAnnotation?.dashboard_name
                    ? annotationModal.dashboardId != existingModalAnnotation.dashboard_id &&
                      `To select this scope, open this annotation on the ${existingModalAnnotation?.dashboard_name} dashboard`
                    : undefined),
            sideIcon:
                existingModalAnnotation?.dashboard_id &&
                existingModalAnnotation?.scope !== AnnotationScope.Dashboard &&
                existingModalAnnotation.dashboard_id !== annotationModal.dashboardId ? (
                    <Link to={urls.dashboard(existingModalAnnotation?.dashboard_id)} target="_blank" targetBlankIcon />
                ) : null,
        },
        {
            value: AnnotationScope.Project,
            label: annotationScopeToName[AnnotationScope.Project],
        },
        {
            value: AnnotationScope.Organization,
            label: annotationScopeToName[AnnotationScope.Organization],
        },
        {
            value: AnnotationScope.Recording,
            label: annotationScopeToName[AnnotationScope.Recording],
            disabledReason: annotationModal.recordingId
                ? undefined
                : 'To select this scope, open this annotation on the target recording',
        },
    ]

    return (
        <LemonModal
            overlayRef={overlayRef}
            contentRef={contentRef}
            isOpen={isModalOpen}
            onClose={closeModal}
            title={existingModalAnnotation ? 'Edit annotation' : 'New annotation'}
            description="Use annotations to comment on insights, dashboards, and recordings."
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
            width={512}
        >
            <Form
                logic={annotationModalLogic}
                formKey="annotationModal"
                id="annotation-modal-form"
                enableFormOnSubmit
                className="deprecated-space-y-4"
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
                        <LemonCalendarSelectInput granularity="minute" />
                    </LemonField>
                    <LemonField name="scope" label="Scope" className="flex-1">
                        <LemonSelect options={scopeOptions} fullWidth />
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
                {!!existingModalAnnotation &&
                existingModalAnnotation.scope === AnnotationScope.Recording &&
                !!existingModalAnnotation.recording_id &&
                !!existingModalAnnotation.date_marker ? (
                    <div className="flex flex-row justify-end">
                        <ViewRecordingButton
                            sessionId={existingModalAnnotation.recording_id}
                            timestamp={existingModalAnnotation.date_marker}
                            inModal={true}
                            type="secondary"
                        />
                    </div>
                ) : null}
            </Form>
        </LemonModal>
    )
}
