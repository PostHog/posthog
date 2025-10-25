import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CyclotronJobInputs } from 'lib/components/CyclotronJob/CyclotronJobInputs'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import MaxTool from 'scenes/max/MaxTool'

import { AvailableFeature, CyclotronJobInputSchemaType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

export function HogFunctionInputs(): JSX.Element {
    const {
        showSource,
        configuration,
        configurationErrors,
        sampleGlobalsWithInputs,
        usesGroups,
        hasGroupsAddon,
        oldInputs,
        newInputs,
        canEditSource,
    } = useValues(hogFunctionConfigurationLogic)

    const {
        setConfigurationValue,
        setOldInputs,
        setNewInputs,
        clearInputsDiff,
        reportAIHogFunctionInputsPrompted,
        reportAIHogFunctionInputsAccepted,
        reportAIHogFunctionInputsRejected,
        reportAIHogFunctionInputsPromptOpen,
    } = useActions(hogFunctionConfigurationLogic)

    const content = (
        <div className={clsx('p-3 rounded border deprecated-space-y-2 bg-surface-primary')}>
            <div className="deprecated-space-y-2">
                {usesGroups && !hasGroupsAddon ? (
                    <LemonBanner type="warning">
                        <span className="flex gap-2 items-center">
                            This function appears to use Groups but you do not have the Groups Analytics addon. Without
                            it, you may see empty values where you use templates like {'"{groups.kind.properties}"'}
                            <PayGateButton feature={AvailableFeature.GROUP_ANALYTICS} type="secondary" />
                        </span>
                    </LemonBanner>
                ) : null}

                <CyclotronJobInputs
                    errors={(configurationErrors.inputs ?? {}) as Record<string, string>}
                    configuration={{
                        inputs_schema: newInputs ?? configuration.inputs_schema ?? [],
                        inputs: configuration.inputs ?? {},
                    }}
                    onInputSchemaChange={(schema) => {
                        // If user manually edits while diff is showing, clear the diff
                        if (oldInputs && newInputs) {
                            clearInputsDiff()
                        }
                        setConfigurationValue('inputs_schema', schema)
                    }}
                    onInputChange={(key, input) => {
                        setConfigurationValue(`inputs.${key}`, input)
                    }}
                    showSource={showSource}
                    sampleGlobalsWithInputs={sampleGlobalsWithInputs}
                />
                {oldInputs && newInputs && (
                    <div className="flex gap-2 items-center p-2 mt-4 rounded border border-dashed bg-surface-secondary">
                        <div className="flex-1 text-center">
                            <span className="text-sm font-medium">Suggested by Max</span>
                        </div>
                        <div className="flex gap-2">
                            <LemonButton
                                status="danger"
                                icon={<IconX />}
                                onClick={() => {
                                    reportAIHogFunctionInputsRejected()
                                    clearInputsDiff()
                                }}
                                tooltipPlacement="top"
                                size="small"
                            >
                                Reject
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                icon={<IconCheck color="var(--success)" />}
                                onClick={() => {
                                    if (newInputs) {
                                        setConfigurationValue('inputs_schema', newInputs)
                                    }
                                    reportAIHogFunctionInputsAccepted()
                                    clearInputsDiff()
                                }}
                                tooltipPlacement="top"
                                size="small"
                            >
                                Accept
                            </LemonButton>
                        </div>
                    </div>
                )}
                {showSource && canEditSource ? (
                    <LemonButton
                        icon={<IconPlus />}
                        size="small"
                        type="secondary"
                        className="my-4"
                        onClick={() => {
                            setConfigurationValue('inputs_schema', [
                                ...(configuration.inputs_schema ?? []),
                                {
                                    type: 'string',
                                    key: `input_${(configuration.inputs_schema?.length ?? 0) + 1}`,
                                    label: '',
                                    required: false,
                                },
                            ])
                        }}
                    >
                        Add input variable
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )

    return (
        <MaxTool
            identifier="create_hog_function_inputs"
            context={{
                current_inputs_schema: configuration.inputs_schema ?? [],
                hog_code: configuration.hog ?? '',
            }}
            callback={(toolOutput: CyclotronJobInputSchemaType[]) => {
                // Store the old inputs before changing
                setOldInputs(configuration.inputs_schema ?? [])
                // Store the new inputs from Max Tool
                setNewInputs(toolOutput)
                // Report that AI was prompted
                reportAIHogFunctionInputsPrompted()
                // Don't immediately update the form - let user accept/reject
            }}
            onMaxOpen={() => {
                reportAIHogFunctionInputsPromptOpen()
            }}
            suggestions={[]}
            introOverride={{
                headline: 'What input variables do you need?',
                description:
                    'Let me help you generate the input variables for your function based on your code and requirements.',
            }}
        >
            {content}
        </MaxTool>
    )
}
