import { useActions, useValues } from 'kea'

import {
    Button,
    Field,
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

import { CyclotronJobInputIntegration } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegration'
import { CyclotronJobInputIntegrationField } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField'

import { CyclotronJobInputSchemaType } from '~/types'

import { alertWizardLogic } from '../alertWizardLogic'
import { clearIntegrationFields } from './clearIntegrationFields'

export function QuillConfigureStep(): JSX.Element {
    const { requiredInputsSchema, configuration, selectedTemplateLoading, submitting, testing } =
        useValues(alertWizardLogic)
    const { setInputValue, submitConfiguration, testConfiguration } = useActions(alertWizardLogic)

    if (selectedTemplateLoading) {
        return (
            <div className="flex flex-col gap-3">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Configure your alert
                </Heading>
                <Skeleton className="h-10" />
                <Skeleton className="h-10" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Configure your alert
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Fill in the details to complete setup
                </Text>
            </div>

            <div className="flex flex-col gap-3">
                {requiredInputsSchema.map((schema: CyclotronJobInputSchemaType) => (
                    <Field key={schema.key}>
                        <FieldLabel htmlFor={`alert-wizard-input-${schema.key}`}>{schema.label}</FieldLabel>
                        <QuillSchemaInput
                            id={`alert-wizard-input-${schema.key}`}
                            schema={schema}
                            value={configuration.inputs?.[schema.key]?.value}
                            onChange={(val) => setInputValue(schema.key, { value: val })}
                            configuration={configuration}
                            onInputChange={setInputValue}
                        />
                    </Field>
                ))}
            </div>

            <div className="flex flex-wrap justify-end gap-2">
                <Button
                    variant="outline"
                    onClick={testConfiguration}
                    loading={testing}
                    disabledReason={submitting ? 'Creating the alert' : undefined}
                >
                    Test
                </Button>
                <Button
                    variant="primary"
                    onClick={submitConfiguration}
                    loading={submitting}
                    disabledReason={testing ? 'Testing the alert' : undefined}
                >
                    Create alert
                </Button>
            </div>
        </div>
    )
}

function QuillSchemaInput({
    id,
    schema,
    value,
    onChange,
    configuration,
    onInputChange,
}: {
    id: string
    schema: CyclotronJobInputSchemaType
    value: any
    onChange: (value: any) => void
    configuration: { inputs_schema: CyclotronJobInputSchemaType[]; inputs: Record<string, any> | null }
    onInputChange: (key: string, value: any) => void
}): JSX.Element {
    if (schema.type === 'integration') {
        return (
            <CyclotronJobInputIntegration
                schema={schema}
                value={value}
                onChange={(newValue) => {
                    clearIntegrationFields(configuration, schema.key, onInputChange)
                    onChange(newValue)
                }}
            />
        )
    }

    if (schema.type === 'integration_field') {
        return (
            <CyclotronJobInputIntegrationField
                schema={schema}
                value={value}
                onChange={onChange}
                configuration={configuration}
            />
        )
    }

    // Autocapture records copied text, so a credential typed here would otherwise reach analytics.
    if (schema.type === 'choice') {
        const choices = schema.choices ?? []

        return (
            <Select items={choices} value={value ?? schema.default} onValueChange={onChange}>
                <SelectTrigger id={id} className="ph-no-capture w-full">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {choices.map((choice) => (
                        <SelectItem key={choice.value} value={choice.value}>
                            {choice.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        )
    }

    return (
        <Input
            id={id}
            className="ph-no-capture"
            value={value ?? ''}
            onChange={(event) => onChange(event.target.value)}
            placeholder={schema.description || schema.label || ''}
        />
    )
}
