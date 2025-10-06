import './FeatureFlagInstructions.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonSelect, Link } from '@posthog/lemon-ui'

import { INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagType, GroupTypeIndex, SDKKey } from '~/types'

import {
    BOOTSTRAPPING_OPTIONS,
    FF_ANCHOR,
    InstructionOption,
    LOCAL_EVALUATION_LIBRARIES,
    LOCAL_EVAL_ANCHOR,
    LibraryType,
    OPTIONS,
    PAYLOADS_ANCHOR,
    PAYLOAD_LIBRARIES,
    REMOTE_CONFIGURATION_LIBRARIES,
} from './FeatureFlagCodeOptions'

function FeatureFlagInstructionsFooter({ documentationLink }: { documentationLink: string }): JSX.Element {
    return (
        <div>
            Need more information?{' '}
            <Link data-attr="feature-flag-doc-link" target="_blank" to={documentationLink} targetBlankIcon>
                Check the docs
            </Link>
        </div>
    )
}

export interface CodeInstructionsProps {
    options: InstructionOption[]
    selectedLanguage?: string
    featureFlag?: FeatureFlagType
    dataAttr?: string
    showFlagValue?: boolean
    showLocalEval?: boolean
    showBootstrap?: boolean
    showAdvancedOptions?: boolean
    showFooter?: boolean
}

export function CodeInstructions({
    options,
    selectedLanguage,
    featureFlag,
    dataAttr = '',
    showLocalEval = false,
    showBootstrap = false,
    showAdvancedOptions = true,
    showFooter = true,
}: CodeInstructionsProps): JSX.Element {
    const encryptedPayload = featureFlag?.has_encrypted_payloads
    const remoteConfiguration = featureFlag?.is_remote_configuration

    const [defaultSelectedOption] = (remoteConfiguration
        ? options.filter((option) => option.key === SDKKey.NODE_JS)
        : options) || [options[0]]

    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)
    const [bootstrapOption, setBootstrapOption] = useState(BOOTSTRAPPING_OPTIONS[0])
    const [showPayloadCode, setShowPayloadCode] = useState(
        featureFlag?.is_remote_configuration || Object.keys(featureFlag?.filters.payloads || {}).length > 0
    )
    const [showLocalEvalCode, setShowLocalEvalCode] = useState(showLocalEval)
    const [showBootstrapCode, setShowBootstrapCode] = useState(showBootstrap)

    const showFlagValueCode = !featureFlag?.is_remote_configuration

    const multivariantFlag = !!featureFlag?.filters.multivariate?.variants

    const featureFlagKey = featureFlag?.key || 'my-flag'

    const { groupTypes } = useValues(groupsModel)
    const groupType =
        featureFlag?.filters?.aggregation_group_type_index != null
            ? groupTypes.get(featureFlag.filters.aggregation_group_type_index as GroupTypeIndex)
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
        const option = options.find((option) => option.key === selectedValue)

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

        const bootstrapOption = BOOTSTRAPPING_OPTIONS.find((bootstrapOption) => bootstrapOption.key === selectedValue)
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
            selectOption(defaultSelectedOption.key)
        }

        if (
            featureFlag?.is_remote_configuration ||
            (Object.keys(featureFlag?.filters.payloads || {}).length > 0 &&
                Object.values(featureFlag?.filters.payloads || {}).some((value) => value))
        ) {
            setShowPayloadCode(true)
        } else {
            setShowPayloadCode(false)
        }

        if (featureFlag?.ensure_experience_continuity) {
            setShowLocalEvalCode(false)
        }
    }, [selectedLanguage, featureFlag]) // oxlint-disable-line react-hooks/exhaustive-deps

    const groups = featureFlag?.filters?.groups || []
    // return first non-instant property in group
    const firstNonInstantProperty = groups
        .find(
            (group) =>
                group.properties?.length &&
                group.properties.some((property) => !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || ''))
        )
        ?.properties?.find((property) => !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || ''))?.key

    const randomProperty = groups.find((group) => group.properties?.length)?.properties?.[0]?.key

    const allFlagLibraries = [
        {
            title: 'Client libraries',
            options: OPTIONS.filter((option) => option.type == LibraryType.Client).map((option) => ({
                value: option.key,
                label: option.value,
                'data-attr': `feature-flag-instructions-select-option-${option.key}`,
                labelInMenu: (
                    <div className="flex items-center deprecated-space-x-2">
                        <option.Icon />
                        <span>{option.value}</span>
                    </div>
                ),
            })),
        },
        {
            title: 'Server libraries',
            options: OPTIONS.filter((option) => option.type == LibraryType.Server).map((option) => ({
                value: option.key,
                label: option.value,
                'data-attr': `feature-flag-instructions-select-option-${option.key}`,
                labelInMenu: (
                    <div className="flex items-center deprecated-space-x-2">
                        <option.Icon />
                        <span>{option.value}</span>
                    </div>
                ),
            })),
        },
    ]
    const remoteConfigurationLibraries = [
        {
            title: 'Server libraries',
            options: OPTIONS.filter((option) => REMOTE_CONFIGURATION_LIBRARIES.includes(option.key)).map((option) => ({
                value: option.key,
                label: option.value,
                'data-attr': `feature-flag-instructions-select-option-${option.key}`,
                labelInMenu: (
                    <div className="flex items-center deprecated-space-x-2">
                        <option.Icon />
                        <span>{option.value}</span>
                    </div>
                ),
            })),
        },
    ]
    const supportedLibraries = remoteConfiguration ? remoteConfigurationLibraries : allFlagLibraries

    return (
        <div className="flex flex-col gap-4">
            {showAdvancedOptions && (
                <div className="flex items-center gap-6">
                    <div>
                        <LemonSelect
                            data-attr={'feature-flag-instructions-select' + (dataAttr ? `-${dataAttr}` : '')}
                            options={supportedLibraries}
                            onChange={(val) => {
                                if (val) {
                                    selectOption(val)
                                    reportFlagsCodeExampleLanguage(val)
                                }
                            }}
                            value={selectedOption.key}
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
                                disabled={!PAYLOAD_LIBRARIES.includes(selectedOption.key)}
                            />
                            <IconInfo className="text-xl text-secondary shrink-0" />
                        </div>
                    </Tooltip>
                    <>
                        <Tooltip
                            title="Bootstrapping is only available client side in our JavaScript and React Native
                                libraries and only works for flags that don't persist across authentication steps"
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
                                        !BOOTSTRAPPING_OPTIONS.map((bo) => bo.key).includes(selectedOption.key) ||
                                        !!featureFlag?.ensure_experience_continuity
                                    }
                                />
                                <IconInfo className="text-xl text-secondary shrink-0" />
                            </div>
                        </Tooltip>
                        <Tooltip title="Local evaluation is only available in server side libraries and only works for flags that don't persist across authentication steps">
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
                                        remoteConfiguration ||
                                        !LOCAL_EVALUATION_LIBRARIES.includes(selectedOption.key) ||
                                        !!featureFlag?.ensure_experience_continuity
                                    }
                                />
                                <IconInfo className="text-xl text-secondary shrink-0" />
                            </div>
                        </Tooltip>
                    </>
                </div>
            )}
            {showLocalEvalCode && (
                <>
                    <h4 className="l4">Local evaluation</h4>
                </>
            )}
            {showFlagValueCode && (
                <selectedOption.Snippet
                    data-attr="feature-flag-instructions-snippet"
                    flagKey={featureFlagKey}
                    multivariant={multivariantFlag}
                    groupType={groupType}
                    localEvaluation={showLocalEvalCode}
                    instantlyAvailableProperties={!firstNonInstantProperty}
                    samplePropertyName={firstNonInstantProperty || randomProperty}
                />
            )}
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
                        remoteConfiguration={remoteConfiguration}
                        encryptedPayload={encryptedPayload}
                    />
                </>
            )}
            {showBootstrapCode && (
                <>
                    <h4 className="l4">Bootstrap</h4>
                    <bootstrapOption.Snippet flagKey={featureFlagKey} />
                </>
            )}
            {showFooter && <FeatureFlagInstructionsFooter documentationLink={getDocumentationLink()} />}
            <div />
        </div>
    )
}

export function FeatureFlagInstructions({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    return <CodeInstructions options={OPTIONS} featureFlag={featureFlag} />
}
