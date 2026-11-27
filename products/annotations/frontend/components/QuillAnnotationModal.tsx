import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTrash, IconX } from '@posthog/icons'
import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { EmojiPickerPopover } from 'lib/components/EmojiPicker/EmojiPickerPopover'
import { LemonTextAreaMarkdown } from 'lib/components/LemonTextAreaMarkdown/LemonTextAreaMarkdown'
import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { shortTimeZone } from 'lib/utils/timezones'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'
import { urls } from 'scenes/urls'

import { AnnotationType } from '~/types'

import { annotationModalLogic } from '../logics/annotationModalLogic'
import { annotationScopeOptions } from './annotationScopeOptions'

/** Quill version of `AnnotationModal`, which the annotations page renders under `today-rail-nav`. */
export function QuillAnnotationModal(): JSX.Element {
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

    const scopeOptions = annotationScopeOptions(existingModalAnnotation, annotationModal.dashboardId, onSavedInsight)

    return (
        <Credenza
            open={isModalOpen}
            onOpenChange={(open) => {
                if (!open) {
                    closeModal()
                }
            }}
            disablePointerDismissal={annotationModalChanged}
        >
            <CredenzaContent className="sm:max-w-128">
                <CredenzaHeader>
                    <CredenzaTitle>{existingModalAnnotation ? 'Edit annotation' : 'New annotation'}</CredenzaTitle>
                    <CredenzaDescription>Use annotations to comment on insights, dashboards</CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <Form
                        logic={annotationModalLogic}
                        formKey="annotationModal"
                        id="annotation-modal-form"
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
                    >
                        <div className="flex flex-wrap gap-2">
                            <div className="min-w-48 flex-1">
                                <QuillSettingFormField
                                    name="dateMarker"
                                    label={
                                        <span>
                                            Date and time (
                                            <Button
                                                variant="link"
                                                size="inline"
                                                nativeButton={false}
                                                render={
                                                    <LinkPrimitive
                                                        to={urls.settings('environment-customization', 'date-and-time')}
                                                        target="_blank"
                                                    />
                                                }
                                            >
                                                {shortTimeZone(timezone)}
                                            </Button>
                                            )
                                        </span>
                                    }
                                >
                                    {({ value, onChange }) => (
                                        <DatePicker
                                            value={value}
                                            onChange={onChange}
                                            granularity="minute"
                                            maxDate={dayjs().add(1, 'year')}
                                        />
                                    )}
                                </QuillSettingFormField>
                            </div>
                            <div className="min-w-48 flex-1">
                                <QuillSettingFormField name="scope" label="Scope">
                                    {({ id, value, onChange }) => (
                                        <Select<AnnotationType['scope']>
                                            items={scopeOptions}
                                            value={value}
                                            onValueChange={onChange}
                                        >
                                            <SelectTrigger id={id} className="w-full">
                                                <SelectValue />
                                            </SelectTrigger>
                                            <SelectContent>
                                                {scopeOptions.map((option) => (
                                                    <SelectItem
                                                        key={option.value}
                                                        value={option.value}
                                                        disabledReason={option.disabledReason || undefined}
                                                    >
                                                        <span className="flex flex-col">
                                                            <span>{option.label}</span>
                                                            {option.tooltip && (
                                                                <Text size="xs" variant="muted" render={<span />}>
                                                                    {option.tooltip}
                                                                </Text>
                                                            )}
                                                        </span>
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    )}
                                </QuillSettingFormField>
                            </div>
                        </div>
                        <QuillSettingFormField name="content" label="Content">
                            {({ value, onChange }) => (
                                <LemonTextAreaMarkdown
                                    value={value}
                                    onChange={onChange}
                                    placeholder="What's this annotation about?"
                                    onPressCmdEnter={submitAnnotationModal}
                                    data-attr="create-annotation-input"
                                    maxLength={400}
                                />
                            )}
                        </QuillSettingFormField>
                        <QuillSettingFormField name="emoji" label="Emoji (optional)">
                            {({ value, onChange }) => (
                                <div className="flex flex-col gap-1">
                                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                        Shown in place of the default badge when this annotation appears on a chart.
                                    </Text>
                                    <div className="flex items-center gap-2">
                                        <EmojiPickerPopover
                                            onSelect={(emoji) => onChange(emoji)}
                                            data-attr="annotation-emoji-picker"
                                        />
                                        {value ? (
                                            <div className="flex items-center gap-1">
                                                <span className="text-2xl leading-none">{value}</span>
                                                <Button
                                                    size="icon-sm"
                                                    tooltip="Remove emoji"
                                                    aria-label="Remove emoji"
                                                    onClick={() => onChange(null)}
                                                    data-attr="annotation-emoji-clear"
                                                >
                                                    <IconX />
                                                </Button>
                                            </div>
                                        ) : (
                                            <Text size="xs" variant="muted" render={<span />}>
                                                No emoji selected
                                            </Text>
                                        )}
                                    </div>
                                </div>
                            )}
                        </QuillSettingFormField>
                        {existingModalAnnotation && (
                            <div className="flex">
                                <Button
                                    variant="destructive-outline"
                                    onClick={() => {
                                        deleteAnnotation(existingModalAnnotation)
                                        closeModal()
                                    }}
                                    data-attr="delete-annotation"
                                >
                                    <IconTrash />
                                    Delete annotation
                                </Button>
                            </div>
                        )}
                    </Form>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button variant="outline" onClick={closeModal}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        type="submit"
                        form="annotation-modal-form"
                        loading={isAnnotationModalSubmitting}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
