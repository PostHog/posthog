import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconCopy } from '@posthog/icons'
import {
    Badge,
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Heading,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
} from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { VariableType } from '~/queries/nodes/DataVisualization/types'

import { VARIABLE_TYPE_OPTIONS, formatVariableReference } from './constants'
import { QuillVariableInsightsTable } from './QuillVariableInsightsTable'
import { QuillVariableSpecificFields } from './QuillVariableSpecificFields'
import { sqlVariableEditSceneLogic } from './sqlVariableEditSceneLogic'
import { toFormVariable } from './toFormVariable'

export interface QuillSqlVariableEditFormProps {
    referenceCodeName: string
    onNameChange: (name: string) => void
}

/** The quill body of the SQL variable edit page. The scene keeps the form, title and save actions. */
export function QuillSqlVariableEditForm({
    referenceCodeName,
    onNameChange,
}: QuillSqlVariableEditFormProps): JSX.Element {
    const { isNew, variableLoading, variableType, variableForm, insightsUsingVariable, insightsUsingVariableLoading } =
        useValues(sqlVariableEditSceneLogic)
    const { setVariableType, setVariableFormValues } = useActions(sqlVariableEditSceneLogic)
    const typeId = useId()

    if (variableLoading) {
        return (
            <div aria-busy aria-label="Loading variable" className="flex flex-col gap-4">
                <Skeleton className="h-10 w-1/3" />
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-30 w-1/2" />
            </div>
        )
    }

    return (
        <>
            <div className="flex max-w-xl flex-col gap-4">
                <QuillSettingFormField name="name" label="Name">
                    {({ id, value, invalid }) => (
                        <>
                            <Input
                                id={id}
                                placeholder="e.g., Start Date"
                                value={value ?? ''}
                                onChange={(event) => onNameChange(event.target.value)}
                                aria-invalid={invalid || undefined}
                            />
                            <FieldDescription>
                                Variable name must be alphanumeric and can only contain spaces and underscores
                            </FieldDescription>
                        </>
                    )}
                </QuillSettingFormField>

                {referenceCodeName && (
                    <div className="flex flex-wrap items-center gap-1">
                        <Text size="xs" variant="muted" render={<span />}>
                            Use this variable by referencing
                        </Text>
                        <Badge className="font-mono" translate="no">
                            {formatVariableReference(referenceCodeName)}
                        </Badge>
                        <Button
                            size="icon-xs"
                            aria-label="Copy to clipboard"
                            tooltip="Copy to clipboard"
                            onClick={() => {
                                copyToClipboard(formatVariableReference(referenceCodeName), 'code')
                            }}
                        >
                            <IconCopy />
                        </Button>
                    </div>
                )}

                <Field>
                    <FieldLabel htmlFor={typeId}>Type</FieldLabel>
                    <Select<VariableType>
                        items={VARIABLE_TYPE_OPTIONS}
                        value={variableType}
                        onValueChange={(value) => value && setVariableType(value)}
                    >
                        <SelectTrigger id={typeId} className="w-full">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {VARIABLE_TYPE_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>

                <QuillVariableSpecificFields
                    variable={toFormVariable(variableForm, variableType)}
                    updateVariable={(updatedVariable) => setVariableFormValues(updatedVariable)}
                />
            </div>

            {!isNew && (
                <div className="mt-8 flex flex-col gap-2">
                    <Heading size="base" render={<h3 className="m-0" />}>
                        Insights using this variable
                    </Heading>
                    <QuillVariableInsightsTable
                        insights={insightsUsingVariable}
                        loading={insightsUsingVariableLoading}
                    />
                </div>
            )}
        </>
    )
}
