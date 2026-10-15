import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegration } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegration'
import { CyclotronJobInputIntegrationField } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { CyclotronJobInputSchemaType } from '~/types'

import { alertWizardLogic } from '../alertWizardLogic'

export function ConfigureStep(): JSX.Element {
    const { requiredInputsSchema, configuration, selectedTemplateLoading, submitting, testing } =
        useValues(alertWizardLogic)
    const { setInputValue, submitConfiguration, testConfiguration } = useActions(alertWizardLogic)

    if (selectedTemplateLoading) {
        return (
            <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-1">Configure your alert</h2>
                <LemonSkeleton className="h-10" />
                <LemonSkeleton className="h-10" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Configure your alert</h2>
                <p className="text-secondary text-sm">Fill in the details to complete setup</p>
            </div>

            <div className="space-y-4">
                {requiredInputsSchema.map((schema: CyclotronJobInputSchemaType) => (
                    <LemonField.Pure key={schema.key} label={schema.label}>
                        <SchemaInput
                            schema={schema}
                            value={configuration.inputs?.[schema.key]?.value}
                            onChange={(val) => setInputValue(schema.key, { value: val })}
                            configuration={configuration}
                            onInputChange={setInputValue}
                        />
                    </LemonField.Pure>
                ))}
            </div>

            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={testConfiguration} loading={testing} disabled={submitting}>
                    Test
                </LemonButton>
                <LemonButton type="primary" onClick={submitConfiguration} loading={submitting} disabled={testing}>
                    Create alert
                </LemonButton>
            </div>
        </div>
    )
}

function SchemaInput({
    schema,
    value,
    onChange,
    configuration,
    onInputChange,
}: {
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
                    configuration.inputs_schema
                        .filter((s) => s.type === 'integration_field' && s.integration_key === schema.key)
                        .forEach((field) => {
                            onInputChange(field.key, { value: null })
                        })
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
    // The standard destination editor guards its inputs the same way.
    if (schema.type === 'choice') {
        return (
            <LemonSelect
                fullWidth
                className="ph-no-capture"
                options={(schema.choices ?? []).map((choice) => ({ value: choice.value, label: choice.label }))}
                value={value ?? schema.default}
                onChange={onChange}
            />
        )
    }

    return (
        <LemonInput
            className="ph-no-capture"
            value={value ?? ''}
            onChange={onChange}
            placeholder={schema.description || schema.label || ''}
        />
    )
}
