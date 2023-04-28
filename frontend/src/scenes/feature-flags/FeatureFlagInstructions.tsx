import { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import { IconInfo, IconOpenInNew } from 'lib/lemon-ui/icons'
import './FeatureFlagInstructions.scss'
import { LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'
import { FeatureFlagType } from '~/types'
import {
    BOOTSTRAPPING_OPTIONS,
    FF_ANCHOR,
    InstructionOption,
    LibraryType,
    LOCAL_EVALUATION_LIBRARIES,
    PAYLOAD_LIBRARIES,
    LOCAL_EVAL_ANCHOR,
    OPTIONS,
    PAYLOADS_ANCHOR,
} from './FeatureFlagCodeOptions'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { groupsModel } from '~/models/groupsModel'

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

export interface CodeInstructionsProps {
    options: InstructionOption[]
    selectedLanguage?: string
    featureFlag?: FeatureFlagType
    dataAttr?: string
    showLocalEval?: boolean
    showBootstrap?: boolean
}

export function CodeInstructions({
    options,
    selectedLanguage,
    featureFlag,
    dataAttr = '',
    showLocalEval = false,
    showBootstrap = false,
}: CodeInstructionsProps): JSX.Element {
    const [defaultSelectedOption] = options
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)
    const [bootstrapOption, setBootstrapOption] = useState(BOOTSTRAPPING_OPTIONS[0])
    const [showPayloadCode, setShowPayloadCode] = useState(Object.keys(featureFlag?.filters.payloads || {}).length > 0)
    const [showLocalEvalCode, setShowLocalEvalCode] = useState(showLocalEval)
    const [showBootstrapCode, setShowBootstrapCode] = useState(showBootstrap)

    const multivariantFlag = !!featureFlag?.filters.multivariate?.variants

    const featureFlagKey = featureFlag?.key || 'my-flag'

    const { groupTypes } = useValues(groupsModel)
    const groupType =
        featureFlag?.filters?.aggregation_group_type_index != null
            ? groupTypes[featureFlag?.filters?.aggregation_group_type_index]
            : undefined

    const { reportFlagsCodeExampleInteraction, reportFlagsCodeExampleLanguage } = useActions(eventUsageLogic)
    const getDocumentationLink = (): string => {
        const documentationLink = selectedOption.documentationLink

        if (showBootstrapCode) {
            return bootstrapOption.documentationLink
        }

        let anchor = FF_ANCHOR
        if (showLocalEvalCode) {
            anchor = LOCAL_EVAL_ANCHOR
        } else if (showPayloadCode) {
            anchor = PAYLOADS_ANCHOR
        }

        return `${documentationLink}${anchor}`
    }

    const selectOption = (selectedValue: string): void => {
        const option = options.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }

        const libHasPayloads = PAYLOAD_LIBRARIES.find((payloadOption) => payloadOption === selectedValue)

        if (!libHasPayloads) {
            setShowPayloadCode(false)
        }

        const libHasLocalEval = LOCAL_EVALUATION_LIBRARIES.find((localEvalOption) => localEvalOption === selectedValue)
        if (!libHasLocalEval) {
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
        } else {
            // When flag definition changes, de-select any options that can't be selected anymore
            selectOption(selectedOption.value)
        }

        if (
            Object.keys(featureFlag?.filters.payloads || {}).length > 0 &&
            Object.values(featureFlag?.filters.payloads || {}).some((value) => value)
        ) {
            setShowPayloadCode(true)
        } else {
            setShowPayloadCode(false)
        }

        if (featureFlag?.ensure_experience_continuity) {
            setShowLocalEvalCode(false)
        }
    }, [selectedLanguage, featureFlag])

    return (
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
                                reportFlagsCodeExampleLanguage(val)
                            }
                        }}
                        value={selectedOption.value}
                    />
                </div>
                <Tooltip
                    title={`Feature flag payloads are only available in these libraries: ${PAYLOAD_LIBRARIES.map(
                        (payloadOption) => ` ${payloadOption}`
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
                            disabled={!PAYLOAD_LIBRARIES.includes(selectedOption.value)}
                        />
                        <IconInfo className="text-xl text-muted-alt shrink-0" />
                    </div>
                </Tooltip>
                <>
                    <Tooltip
                        title="Bootstrapping is only available client side in our JavaScript and React Native
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
                                    !BOOTSTRAPPING_OPTIONS.map((bo) => bo.value).includes(selectedOption.value) ||
                                    !!featureFlag?.ensure_experience_continuity
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
                                    !LOCAL_EVALUATION_LIBRARIES.includes(selectedOption.value) ||
                                    !!featureFlag?.ensure_experience_continuity
                                }
                            />
                            <IconInfo className="text-xl text-muted-alt shrink-0" />
                        </div>
                    </Tooltip>
                </>
            </div>
            <div className="mt-4 mb">
                {showLocalEvalCode && (
                    <>
                        <h4 className="l4">Local evaluation</h4>
                    </>
                )}
                <selectedOption.Snippet
                    data-attr="feature-flag-instructions-snippet"
                    flagKey={featureFlagKey}
                    multivariant={multivariantFlag}
                    groupType={groupType}
                    localEvaluation={showLocalEvalCode}
                />
                {showPayloadCode && (
                    <>
                        <h4 className="l4">Payload</h4>
                        <selectedOption.Snippet
                            data-attr="feature-flag-instructions-payload-snippet"
                            flagKey={featureFlagKey}
                            multivariant={multivariantFlag}
                            groupType={groupType}
                            localEvaluation={showLocalEvalCode}
                            payload={true}
                        />
                    </>
                )}
                {showBootstrapCode && (
                    <>
                        <h4 className="l4">Bootstrap</h4>
                        <bootstrapOption.Snippet flagKey={featureFlagKey} />
                    </>
                )}
                <FeatureFlagInstructionsFooter documentationLink={getDocumentationLink()} />
            </div>
            <div />
        </div>
    )
}

export function FeatureFlagInstructions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return <CodeInstructions options={OPTIONS} featureFlag={featureFlag} />
}
