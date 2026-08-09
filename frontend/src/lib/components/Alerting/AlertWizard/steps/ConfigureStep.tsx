import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CyclotronJobInputIntegration } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegration'
import { CyclotronJobInputIntegrationField } from 'lib/components/CyclotronJob/integrations/CyclotronJobInputIntegrationField'
import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { CyclotronJobInputSchemaType } from '~/types'

import { alertWizardLogic } from '../alertWizardLogic'

export function ConfigureStep(): JSX.Element {
    const { requiredInputsSchema, configuration, selectedTemplateLoading, submitting, testing } =
        useValues(alertWizardLogic)
    const { setInputValue, testConfiguration } = useActions(alertWizardLogic)

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
                <CreateAlertButton />
            </div>
        </div>
    )
}

// Finds the Slack channel field on the current template (if any) and the integration it points at,
// so the create button can gate on channel selection and app membership.
function findSlackChannelTarget(configuration: {
    inputs_schema: CyclotronJobInputSchemaType[]
    inputs: Record<string, any> | null
}): { integrationId: number; channelValue: string | undefined } | null {
    const channelSchema = configuration.inputs_schema.find(
        (s) => s.type === 'integration_field' && s.integration_field === 'slack_channel'
    )
    if (!channelSchema?.integration_key) {
        return null
    }
    const integrationId = configuration.inputs?.[channelSchema.integration_key]?.value
    if (typeof integrationId !== 'number') {
        return null
    }
    return { integrationId, channelValue: configuration.inputs?.[channelSchema.key]?.value }
}

function CreateAlertButton(): JSX.Element {
    const { configuration, submitting, testing } = useValues(alertWizardLogic)
    const { submitConfiguration } = useActions(alertWizardLogic)

    const slackTarget = findSlackChannelTarget(configuration)
    if (slackTarget) {
        return (
            <SlackChannelAwareCreateButton
                integrationId={slackTarget.integrationId}
                channelValue={slackTarget.channelValue}
                submitting={submitting}
                testing={testing}
                onSubmit={submitConfiguration}
            />
        )
    }

    return (
        <LemonButton type="primary" onClick={submitConfiguration} loading={submitting} disabled={testing}>
            Create alert
        </LemonButton>
    )
}

// Blocks the submit while the Slack channel is unresolved or the PostHog app is not in it — the
// same `isMemberOfSlackChannel` signal that drives the picker's warning. Without this the user can
// create an alert that never delivers, then start over when nothing arrives.
function SlackChannelAwareCreateButton({
    integrationId,
    channelValue,
    submitting,
    testing,
    onSubmit,
}: {
    integrationId: number
    channelValue: string | undefined
    submitting: boolean
    testing: boolean
    onSubmit: () => void
}): JSX.Element {
    const { isMemberOfSlackChannel } = useValues(slackIntegrationLogic({ id: integrationId }))

    const disabledReason = testing
        ? 'Wait for the test to finish'
        : !channelValue
          ? 'Select a Slack channel to continue'
          : isMemberOfSlackChannel(channelValue) === false
            ? 'Add the PostHog Slack app to this channel, then check again'
            : undefined

    return (
        <LemonButton type="primary" onClick={onSubmit} loading={submitting} disabledReason={disabledReason}>
            Create alert
        </LemonButton>
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

    return <LemonInput value={value ?? ''} onChange={onChange} placeholder={schema.description || schema.label || ''} />
}
