import { useEffect, useState } from 'react'

import { Card, Row } from 'antd'
import { IconFlag, IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import {
    UTM_TAGS,
    APISnippet,
    JSSnippet,
    PythonSnippet,
    NodeJSSnippet,
    PHPSnippet,
    RubySnippet,
    GolangSnippet,
    NodeLocalEvaluationSnippet,
    PHPLocalEvaluationSnippet,
    RubyLocalEvaluationSnippet,
    PythonLocalEvaluationSnippet,
    JSBootstrappingSnippet,
    ReactNativeSnippet,
    iOSSnippet,
    AndroidSnippet,
} from 'scenes/feature-flags/FeatureFlagSnippets'

import './FeatureFlagInstructions.scss'
import { JSPayloadSnippet, NodeJSPayloadSnippet } from 'scenes/feature-flags/FeatureFlagPayloadSnippets'
import { LemonSelect } from '@posthog/lemon-ui'

const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'
const LOCAL_EVAL_ANCHOR = '#local-evaluation'
const BOOTSTRAPPING_ANCHOR = '#bootstrapping-flags'

interface InstructionOption {
    value: string
    documentationLink: string
    Snippet: ({ flagKey }: { flagKey: string }) => JSX.Element
    type: LibraryType
}

enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

export const OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: JSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}integrate/client/android${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}integrate/client/ios${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: iOSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: ReactNativeSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: RubySnippet,
        type: LibraryType.Server,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/post-only-endpoints#example-request--response-decide-v2`,
        Snippet: APISnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
]

const LOCAL_EVALUATION_OPTIONS: InstructionOption[] = [
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: NodeLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: PHPLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: RubyLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${LOCAL_EVAL_ANCHOR}`,
        Snippet: PythonLocalEvaluationSnippet,
        type: LibraryType.Server,
    },
]

const BOOTSTRAPPING_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}integrate/client/react-native${UTM_TAGS}${BOOTSTRAPPING_ANCHOR}`,
        Snippet: JSBootstrappingSnippet,
        type: LibraryType.Client,
    },
]

function FeatureFlagInstructionsHeader({
    selectedOptionValue,
    selectOption,
    headerPrompt,
    options,
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
    headerPrompt: string
    options: InstructionOption[]
}): JSX.Element {
    return (
        <Row className="FeatureFlagInstructionsHeader" justify="space-between" align="middle">
            <div className="FeatureFlagInstructionsHeader__header-title">
                <IconFlag className="FeatureFlagInstructionsHeader__header-title__icon" />
                <b>{headerPrompt}</b>
            </div>
            <LemonSelect
                data-attr="feature-flag-instructions-select"
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
}: {
    featureFlagKey: string
    options: InstructionOption[]
    headerPrompt: string
    selectedLanguage?: string
}): JSX.Element {
    const [defaultSelectedOption] = options
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)

    const selectOption = (selectedValue: string): void => {
        const option = options.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }
    }
    useEffect(() => {
        if (selectedLanguage) {
            selectOption(selectedLanguage)
        }
    }, [selectedLanguage])

    return (
        <Card size="small">
            <FeatureFlagInstructionsHeader
                options={options}
                headerPrompt={headerPrompt}
                selectedOptionValue={selectedOption.value}
                selectOption={selectOption}
            />
            <LemonDivider />
            <div className="mt mb">
                <selectedOption.Snippet data-attr="feature-flag-instructions-snippet" flagKey={featureFlagKey} />
            </div>
            <LemonDivider />
            <FeatureFlagInstructionsFooter documentationLink={selectedOption.documentationLink} />
        </Card>
    )
}

export function FeatureFlagInstructions({
    featureFlagKey,
    language,
}: {
    featureFlagKey: string
    language?: string
}): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={featureFlagKey}
            headerPrompt="Learn how to use feature flags in your code"
            options={OPTIONS}
            selectedLanguage={language}
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

const PAYLOAD_OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: JSPayloadSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Snippet: NodeJSPayloadSnippet,
        type: LibraryType.Server,
    },
]

export function FeatureFlagPayloadInstructions({ featureFlagKey }: { featureFlagKey: string }): JSX.Element {
    return (
        <CodeInstructions
            featureFlagKey={featureFlagKey}
            headerPrompt="Using feature flag payloads in your code"
            options={PAYLOAD_OPTIONS}
        />
    )
}
