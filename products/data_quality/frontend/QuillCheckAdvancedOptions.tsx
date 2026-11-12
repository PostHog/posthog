import { useActions, useValues } from 'kea'

import {
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Input,
    Label,
    RadioGroup,
    RadioGroupItem,
    Textarea,
} from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import { CheckTypeEnumApi, DataQualityCheckSeverityEnumApi } from './generated/api.schemas'
import { QuillCheckFormField } from './QuillCheckFormField'
import { QuillCheckNumberInput } from './QuillCheckNumberInput'

const WINDOW_PLACEHOLDER_HOURS = '24'

const SEVERITY_OPTIONS = [
    { value: DataQualityCheckSeverityEnumApi.Error, label: 'Error' },
    { value: DataQualityCheckSeverityEnumApi.Warn, label: 'Warning' },
]

function LookbackFields(): JSX.Element | null {
    const { checkForm, subjectTimeColumn, relationshipSubjects, relationshipTargetTimeColumn } =
        useValues(dataQualityCheckEditorLogic)
    const showSubjectWindow = !!subjectTimeColumn && checkForm.checkType !== CheckTypeEnumApi.CustomSql
    const showTargetWindow = !!relationshipTargetTimeColumn && checkForm.checkType === CheckTypeEnumApi.Relationships
    const targetName =
        relationshipSubjects.find((subject) => subject.id === checkForm.toSubjectUuid)?.name ?? 'the referenced table'

    return (
        <>
            {showSubjectWindow && (
                <QuillCheckFormField
                    name="lookbackHours"
                    label="Only check recent rows"
                    optional
                    description={`Hours to check, by ${subjectTimeColumn}. Leave empty to check the whole table, which costs more to run.`}
                >
                    {({ id, value, onChange, invalid }) => (
                        <QuillCheckNumberInput
                            id={id}
                            value={value}
                            onChange={onChange}
                            invalid={invalid}
                            min={1}
                            placeholder={WINDOW_PLACEHOLDER_HOURS}
                        />
                    )}
                </QuillCheckFormField>
            )}
            {showTargetWindow && (
                <QuillCheckFormField
                    name="toLookbackHours"
                    label="Only look for a match in recent rows"
                    optional
                    description={`Hours of ${targetName} to look in, by ${relationshipTargetTimeColumn}. Leave empty to look in all of it.`}
                >
                    {({ id, value, onChange, invalid }) => (
                        <QuillCheckNumberInput
                            id={id}
                            value={value}
                            onChange={onChange}
                            invalid={invalid}
                            min={1}
                            placeholder={WINDOW_PLACEHOLDER_HOURS}
                        />
                    )}
                </QuillCheckFormField>
            )}
        </>
    )
}

export function QuillCheckAdvancedOptions(): JSX.Element {
    const { advancedOptionsSetCount, advancedOptionsOpen } = useValues(dataQualityCheckEditorLogic)
    const { setAdvancedOptionsOpen } = useActions(dataQualityCheckEditorLogic)

    return (
        <Collapsible open={advancedOptionsOpen} onOpenChange={setAdvancedOptionsOpen}>
            <CollapsibleTrigger data-attr="data-quality-check-advanced-options">
                Advanced options
                {advancedOptionsSetCount > 0 && (
                    <Badge variant="info" aria-label={`${advancedOptionsSetCount} changed from the default`}>
                        {advancedOptionsSetCount}
                    </Badge>
                )}
            </CollapsibleTrigger>
            <CollapsibleContent>
                <div className="flex flex-col gap-4 pt-2">
                    <LookbackFields />
                    <QuillCheckFormField
                        name="name"
                        label="Name"
                        optional
                        description="Lets you refer to this check by name in SQL and the API instead of by its id. Letters, numbers and underscores, starting with a letter."
                    >
                        {({ id, value, onChange, invalid }) => (
                            <Input
                                id={id}
                                value={value ?? ''}
                                onChange={(event) => onChange(event.target.value)}
                                aria-invalid={invalid || undefined}
                                placeholder="orders_customer_id_not_null"
                                data-attr="data-quality-check-name"
                            />
                        )}
                    </QuillCheckFormField>
                    <QuillCheckFormField
                        name="description"
                        label="Description"
                        optional
                        description="Why this check exists and what a failure means. Shown to whoever finds the check failing."
                    >
                        {({ id, value, onChange, invalid }) => (
                            <Textarea
                                id={id}
                                value={value ?? ''}
                                onChange={(event) => onChange(event.target.value)}
                                aria-invalid={invalid || undefined}
                                placeholder="Every order has to belong to a customer"
                                rows={2}
                                data-attr="data-quality-check-description"
                            />
                        )}
                    </QuillCheckFormField>
                    <QuillCheckFormField name="severity" label="Severity">
                        {({ id, value, onChange }) => (
                            <RadioGroup
                                id={id}
                                value={value}
                                onValueChange={(severity) => onChange(severity)}
                                className="flex flex-row flex-wrap gap-4"
                            >
                                {SEVERITY_OPTIONS.map((option) => (
                                    <Label key={option.value} className="flex items-center gap-2">
                                        <RadioGroupItem value={option.value} />
                                        {option.label}
                                    </Label>
                                ))}
                            </RadioGroup>
                        )}
                    </QuillCheckFormField>
                    <QuillCheckFormField name="tags" label="Tags" optional>
                        {({ value, onChange }) => (
                            <TagsCombobox
                                value={value ?? []}
                                onChange={onChange}
                                placeholder="Add a tag"
                                dataAttr="data-quality-check-tags"
                            />
                        )}
                    </QuillCheckFormField>
                </div>
            </CollapsibleContent>
        </Collapsible>
    )
}
