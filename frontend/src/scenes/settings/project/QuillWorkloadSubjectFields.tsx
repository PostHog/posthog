import { Field as KeaField } from 'kea-forms'

import { IconSearch } from '@posthog/icons'
import { Button, Field, FieldDescription, FieldError, FieldLabel, Input } from '@posthog/quill'

export function QuillWorkloadSubjectFields({
    subjectNameLabel,
    subjectNameHelp,
    subjectNamePlaceholder,
    subjectLabel,
    subjectHelp,
    subjectPlaceholder,
    canLookUp,
    onLookUp,
    onPressEnter,
    lookUpLoading,
    lookUpDisabledReason,
}: {
    subjectNameLabel: string
    subjectNameHelp: string | undefined
    subjectNamePlaceholder: string | undefined
    subjectLabel: string
    subjectHelp: string | undefined
    subjectPlaceholder: string | undefined
    canLookUp: boolean
    onLookUp: () => void
    onPressEnter: (() => void) | undefined
    lookUpLoading: boolean
    lookUpDisabledReason: string | undefined
}): JSX.Element {
    return (
        <>
            <KeaField name="subject_name" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>{subjectNameLabel}</FieldLabel>
                        <div className="flex flex-wrap gap-2 w-full">
                            <Input
                                id={id}
                                value={value ?? ''}
                                onChange={(event) => onChange(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' && onPressEnter) {
                                        event.preventDefault()
                                        onPressEnter()
                                    }
                                }}
                                placeholder={subjectNamePlaceholder}
                                className="flex-1 min-w-40"
                                data-attr="workload-trust-policy-subject-name"
                            />
                            {canLookUp ? (
                                <Button
                                    variant="outline"
                                    onClick={onLookUp}
                                    loading={lookUpLoading}
                                    disabledReason={lookUpDisabledReason}
                                    data-attr="workload-trust-policy-look-up-subject"
                                >
                                    <IconSearch />
                                    Look up
                                </Button>
                            ) : null}
                        </div>
                        {subjectNameHelp && <FieldDescription>{subjectNameHelp}</FieldDescription>}
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>
            <KeaField name="subject" noStyle>
                {({ id, value, onChange, error }) => (
                    <Field data-invalid={error ? true : undefined}>
                        <FieldLabel htmlFor={id}>{subjectLabel}</FieldLabel>
                        <Input
                            id={id}
                            value={value ?? ''}
                            onChange={(event) => onChange(event.target.value)}
                            placeholder={subjectPlaceholder}
                            data-attr="workload-trust-policy-subject"
                        />
                        {subjectHelp && <FieldDescription>{subjectHelp}</FieldDescription>}
                        {error && <FieldError>{error}</FieldError>}
                    </Field>
                )}
            </KeaField>
        </>
    )
}
