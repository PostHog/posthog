import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal, LemonModalProps, LemonSelect, LemonSelectOptions, Link } from '@posthog/lemon-ui'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { LemonTextAreaMarkdown } from 'lib/components/LemonTextAreaMarkdown/LemonTextAreaMarkdown'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { shortTimeZone } from 'lib/utils/timezones'
import { urls } from 'scenes/urls'

import { AnnotationScope, AnnotationType } from '~/types'

import { annotationModalLogic } from '../logics/annotationModalLogic'
import { annotationScopeOptions } from './annotationScopeOptions'

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
        annotationModalChanged,
        isAnnotationModalSubmitting,
        onSavedInsight,
        timezone,
    } = useValues(annotationModalLogic)
    const { closeModal, deleteAnnotation, submitAnnotationModal } = useActions(annotationModalLogic)

    const scopeOptions: LemonSelectOptions<AnnotationType['scope'] | null> = annotationScopeOptions(
        existingModalAnnotation,
        annotationModal.dashboardId,
        onSavedInsight
    ).map(({ link, ...option }) =>
        // Only the insight and dashboard scopes take a side icon, because any side icon, null included, replaces
        // the select's chevron when that option is picked.
        option.value === AnnotationScope.Insight || option.value === AnnotationScope.Dashboard
            ? { ...option, sideIcon: link ? <Link to={link} target="_blank" targetBlankIcon /> : null }
            : option
    )

    return (
        <LemonModal
            overlayRef={overlayRef}
            contentRef={contentRef}
            isOpen={isModalOpen}
            onClose={closeModal}
            hasUnsavedInput={annotationModalChanged}
            title={existingModalAnnotation ? 'Edit annotation' : 'New annotation'}
            description="Use annotations to comment on insights, dashboards"
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
                            Save
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
                                <Link to={urls.settings('environment-customization', 'date-and-time')} target="_blank">
                                    {shortTimeZone(timezone)}
                                </Link>
                                )
                            </span>
                        }
                        className="flex-1"
                    >
                        {({ value, onChange }) => (
                            <DatePicker
                                value={value}
                                onChange={onChange}
                                granularity="minute"
                                maxDate={dayjs().add(1, 'year')}
                            />
                        )}
                    </LemonField>
                    <LemonField name="scope" label="Scope" className="flex-1">
                        <LemonSelect options={scopeOptions} fullWidth />
                    </LemonField>
                </div>
                <LemonField name="content" label="Content">
                    <LemonTextAreaMarkdown
                        placeholder="What's this annotation about?"
                        onPressCmdEnter={submitAnnotationModal}
                        data-attr="create-annotation-input"
                        maxLength={400}
                    />
                </LemonField>
                <LemonField
                    name="emoji"
                    label="Emoji"
                    showOptional
                    info="Shown in place of the default badge when this annotation appears on a chart."
                >
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <EmojiPickerPopover
                                onSelect={(emoji) => onChange(emoji)}
                                data-attr="annotation-emoji-picker"
                            />
                            {value ? (
                                <div className="flex items-center gap-1">
                                    <span className="text-2xl leading-none">{value}</span>
                                    <LemonButton
                                        size="small"
                                        icon={<IconX />}
                                        tooltip="Remove emoji"
                                        onClick={() => onChange(null)}
                                        data-attr="annotation-emoji-clear"
                                    />
                                </div>
                            ) : (
                                <span className="text-secondary text-sm">No emoji selected</span>
                            )}
                        </div>
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
