import { useEffect, useState } from 'react'
import { useActions } from 'kea'
import { Card, Row } from 'antd'
import { IconFlag, IconInfo, IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import './FeatureFlagInstructions.scss'
import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'
import { FeatureFlagType } from '~/types'
import {
    BOOTSTRAPPING_OPTIONS,
    InstructionOption,
    LibraryType,
    LOCAL_EVALUATION_OPTIONS,
    MULTIVARIATE_OPTIONS,
    OPTIONS,
    PAYLOAD_OPTIONS,
} from './FeatureFlagCodeOptions'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

function FeatureFlagInstructionsHeader({
    selectedOptionValue,
    selectOption,
    headerPrompt,
    options,
    dataAttr,
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
    headerPrompt: string
    options: InstructionOption[]
    dataAttr?: string
}): JSX.Element {
    return (
        <Row className="FeatureFlagInstructionsHeader" justify="space-between" align="middle">
            <div className="FeatureFlagInstructionsHeader__header-title">
                <IconFlag className="FeatureFlagInstructionsHeader__header-title__icon" />
                <b>{headerPrompt}</b>
            </div>
            <LemonSelect
                data-attr={'feature-flag-instructions-select' + (dataAttr ? `-${dataAttr}` : '')}
                options={[
                    {
                        title: 'Client libraries',
                        options: options
                            .filter((option) => option.type == LibraryType.Client)
                            .map((option) => ({
                                value: option.value,
                                label: option.value,
                                'data-attr': `feature-flag-instructions-select-option-${option.value}`,
                            })),
                    },
                    {
                        title: 'Server libraries',
                        options: options
                            .filter((option) => option.type == LibraryType.Server)
                            .map((option) => ({
                                value: option.value,
                                label: option.value,
                                'data-attr': `feature-flag-instructions-select-option-${option.value}`,
                            })),
                    },
                ]}
                onChange={(val) => {
                    if (val) {
                        selectOption(val)
                    }
                }}
                value={selectedOptionValue}
            />
        </Row>
    )
}

function FeatureFlagInstructionsFooter({ documentationLink }: { documentationLink: string }): JSX.Element {
    return (
        <div className="mt-4">
            Need more information?{' '}
            <a data-attr="feature-flag-doc-link" target="_blank" rel="noopener" href={documentationLink}>
                Check the docs <IconOpenInNew />
            </a>
        </div>
    )
}

export function CodeInstructions({
    featureFlagKey,
    options,
    headerPrompt,
    selectedLanguage,
    newCodeExample,
    featureFlag,
    dataAttr = '',
}: {
    featureFlagKey: string
    options: InstructionOption[]
    headerPrompt: string
    selectedLanguage?: string
    newCodeExample?: boolean
    featureFlag?: FeatureFlagType
    dataAttr?: string
}): JSX.Element {
    const [defaultSelectedOption] = options
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)
    const [payloadOption, setPayloadOption] = useState(PAYLOAD_OPTIONS[0])
    const [localEvalOption, setLocalEvalOption] = useState(LOCAL_EVALUATION_OPTIONS[0])
    const [bootstrapOption, setBootstrapOption] = useState(BOOTSTRAPPING_OPTIONS[0])
    const [showPayloadCode, setShowPayloadCode] = useState(Object.keys(featureFlag?.filters.payloads || {}).length > 0)
    const [showLocalEvalCode, setShowLocalEvalCode] = useState(false)
    const [showBootstrapCode, setShowBootstrapCode] = useState(false)

    const { reportFlagsCodeExampleInteraction } = useActions(eventUsageLogic)

    const selectOption = (selectedValue: string): void => {
        const option = options.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }

        const payloadOption = PAYLOAD_OPTIONS.find((payloadOption) => payloadOption.value === selectedValue)
        if (payloadOption) {
            setPayloadOption(payloadOption)
        } else {
            setShowPayloadCode(false)
        }

        const localEvalOption = LOCAL_EVALUATION_OPTIONS.find(
            (localEvalOption) => localEvalOption.value === selectedValue
        )
        if (localEvalOption) {
            setLocalEvalOption(localEvalOption)
        } else {
            setShowLocalEvalCode(false)
        }

        const bootstrapOption = BOOTSTRAPPING_OPTIONS.find((bootstrapOption) => bootstrapOption.value === selectedValue)
        if (bootstrapOption) {
            setBootstrapOption(bootstrapOption)
        } else {
            setShowBootstrapCode(false)
        }
    }
    useEffect(() => {
        if (selectedLanguage) {
            selectOption(selectedLanguage)
        }
        if (Object.keys(featureFlag?.filters.payloads || {}).length > 0) {
            setShowPayloadCode(true)
        }
        if (featureFlag?.filters.multivariate?.variants || !featureFlag?.filters.multivariate) {
            selectOption(selectedOption.value)
        }
        if (featureFlag?.ensure_experience_continuity) {
            setShowLocalEvalCode(false)
        }
    }, [selectedLanguage, featureFlag])

    return (
        <>
            {newCodeExample ? (
                <div>
                    <div className="flex items-center gap-6">
                        <div>
                            <LemonSelect
                                data-attr={'feature-flag-instructions-select' + (dataAttr ? `-${dataAttr}` : '')}
                                options={[
                                    {
                                        title: 'Client libraries',
                                        options: OPTIONS.filter((option) => option.type == LibraryType.Client).map(
                                            (option) => ({
                                                value: option.value,
                                                label: option.value,
                                                'data-attr': `feature-flag-instructions-select-option-${option.value}`,
                                            })
                                        ),
                                    },
                                    {
                                        title: 'Server libraries',
                                        options: OPTIONS.filter((option) => option.type == LibraryType.Server).map(
                                            (option) => ({
                                                value: option.value,
                                                label: option.value,
                                                'data-attr': `feature-flag-instructions-select-option-${option.value}`,
                                            })
                                        ),
                                    },
                                ]}
                                onChange={(val) => {
                                    if (val) {
                                        selectOption(val)
                                    }
                                }}
                                value={selectedOption.value}
                            />
                        </div>
                        <Tooltip
                            title={`Feature flag payloads are only available in these libraries: ${PAYLOAD_OPTIONS.map(
                                (payloadOption) => ` ${payloadOption.value}`
                            )}`}
                        >
                            <div className="flex items-center gap-1">
                                <LemonCheckbox
                                    label="Show payload option"
                                    onChange={() => {
                                        setShowPayloadCode(!showPayloadCode)
                                        reportFlagsCodeExampleInteraction('payloads')
                                    }}
                                    data-attr="flags-code-example-payloads-option"
                                    checked={showPayloadCode}
                                    disabled={
                                        !PAYLOAD_OPTIONS.map((payloadOption) => payloadOption.value).includes(
                                            selectedOption.value
                                        )
                                    }
                                />
                                <IconInfo className="text-xl text-muted-alt shrink-0" />
                            </div>
                        </Tooltip>
                        <>
                            <Tooltip
                                title="Bootstrapping is only available client side in our JavaScript and ReactNative
                                        libraries."
                            >
                                <div className="flex items-center gap-1">
                                    <LemonCheckbox
                                        label="Show bootstrap option"
                                        data-attr="flags-code-example-bootstrap-option"
                                        checked={showBootstrapCode}
                                        onChange={() => {
                                            setShowBootstrapCode(!showBootstrapCode)
                                            reportFlagsCodeExampleInteraction('bootstrap')
                                        }}
                                        disabled={
                                            !BOOTSTRAPPING_OPTIONS.map((bo) => bo.value).includes(
                                                selectedOption.value
                                            ) || !!featureFlag?.ensure_experience_continuity
                                        }
                                    />
                                    <IconInfo className="text-xl text-muted-alt shrink-0" />
                                </div>
                            </Tooltip>
                            <Tooltip
                                title="Local evaluation is only available in server side libraries and without flag
                                        persistence."
                            >
                                <div className="flex items-center gap-1">
                                    <LemonCheckbox
                                        label="Show local evaluation option"
                                        data-attr="flags-code-example-local-eval-option"
                                        checked={showLocalEvalCode}
                                        onChange={() => {
                                            setShowLocalEvalCode(!showLocalEvalCode)
                                            reportFlagsCodeExampleInteraction('local evaluation')
                                        }}
                                        disabled={
                                            selectedOption.type !== LibraryType.Server ||
                                            selectedOption.value === 'API' ||
                                            !!featureFlag?.ensure_experience_continuity
                                        }
                                    />
                                    <IconInfo className="text-xl text-muted-alt shrink-0" />
                                </div>
                            </Tooltip>
                        </>
                    </div>
                    <div className="mt-4 mb">
                        {!showLocalEvalCode && (
                            <selectedOption.Snippet
                                data-attr="feature-flag-instructions-snippet"
                                flagKey={featureFlagKey}
                            />
                        )}
                        {showPayloadCode && (
                            <>
                                <h3>Payloads</h3>
                                <payloadOption.Snippet flagKey={featureFlagKey} />
                            </>
                        )}
                        {showLocalEvalCode && (
                            <>
                                <h3>Local evaluation</h3>
                                <localEvalOption.Snippet flagKey={featureFlagKey} />
                            </>
                        )}
                        {showBootstrapCode && (
                            <>
                                <h3>Bootstrapping</h3>
                                <bootstrapOption.Snippet flagKey={featureFlagKey} />
                            </>
                        )}
                        <FeatureFlagInstructionsFooter documentationLink={selectedOption.documentationLink} />
                    </div>
                    <div />
                </div>
            ) : (
                <Card size="small">
                    <FeatureFlagInstructionsHeader
                        dataAttr={dataAttr}
                        options={options}
                        headerPrompt={headerPrompt}
                        selectedOptionValue={selectedOption.value}
                        selectOption={selectOption}
                    />
                    <LemonDivider />
                    <div className="mt mb">
                        <selectedOption.Snippet
                            data-attr="feature-flag-instructions-snippet"
                            flagKey={featureFlagKey}
                        />
                    </div>
                    <LemonDivider />
                    <FeatureFlagInstructionsFooter documentationLink={selectedOption.documentationLink} />
                </Card>
            )}
        </>
    )
}

export function FeatureFlagInstructions({
    featureFlagKey,
    newCodeExample,
    language,
    featureFlag,
}: {
    featureFlagKey: string
    newCodeExample?: boolean
    language?: string
    featureFlag?: FeatureFlagType
}): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={featureFlagKey}
            headerPrompt="Learn how to use feature flags in your code"
            options={featureFlag?.filters.multivariate?.variants ? MULTIVARIATE_OPTIONS : OPTIONS}
            selectedLanguage={language}
            newCodeExample={newCodeExample}
            featureFlag={featureFlag}
        />
    )
}

export function FeatureFlagMultivariateInstructions({ featureFlagKey }: { featureFlagKey: string }): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={featureFlagKey}
            headerPrompt="Learn how to use multivariate flags"
            options={MULTIVARIATE_OPTIONS}
        />
    )
}

export function FeatureFlagLocalEvaluationInstructions({
    featureFlagKey,
    language,
}: {
    featureFlagKey: string
    language?: string
}): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={featureFlagKey}
            headerPrompt="Learn how to use local evaluation"
            options={LOCAL_EVALUATION_OPTIONS}
            selectedLanguage={language}
        />
    )
}

export function FeatureFlagBootstrappingInstructions({ language }: { language: string }): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={''}
            headerPrompt="Learn how to use bootstrapping"
            options={BOOTSTRAPPING_OPTIONS}
            selectedLanguage={language}
        />
    )
}

export function FeatureFlagPayloadInstructions({ featureFlagKey }: { featureFlagKey: string }): JSX.Element {
    return (
        <CodeInstructions
            dataAttr="payload"
            featureFlagKey={featureFlagKey}
            headerPrompt="Using feature flag payloads in your code"
            options={PAYLOAD_OPTIONS}
        />
    )
}
