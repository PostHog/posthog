import { useState } from 'react'

import { Card, Select, Row } from 'antd'
import {
    IconFlag,
    IconJavascript,
    IconPython,
    IconOpenInNew,
    IconNodeJS,
    IconPHP,
    IconRuby,
    IconGolang,
    LemonIconProps,
} from 'lib/lemon-ui/icons'
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
} from 'scenes/feature-flags/FeatureFlagSnippets'

import './FeatureFlagInstructions.scss'
import { JSPayloadSnippet, NodeJSPayloadSnippet } from 'scenes/feature-flags/FeatureFlagPayloadSnippets'

const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'

interface InstructionOption {
    value: string
    documentationLink: string
    Icon: (props: LemonIconProps) => JSX.Element
    Snippet: ({ flagKey }: { flagKey: string }) => JSX.Element
}

const OPTIONS: InstructionOption[] = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSSnippet,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSSnippet,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}integrations/php-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPHP,
        Snippet: PHPSnippet,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}integrations/ruby-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconRuby,
        Snippet: RubySnippet,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}integrations/go-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconGolang,
        Snippet: GolangSnippet,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}integrations/python-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPython,
        Snippet: PythonSnippet,
    },
    {
        value: 'API',
        documentationLink: `${DOC_BASE_URL}api/feature-flags${UTM_TAGS}`,
        Icon: IconOpenInNew,
        Snippet: APISnippet,
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

            <Select
                data-attr="feature-flag-instructions-select"
                value={selectedOptionValue}
                style={{ width: 140 }}
                onChange={selectOption}
            >
                {options.map(({ value, Icon }, index) => (
                    <Select.Option
                        data-attr={'feature-flag-instructions-select-option-' + value}
                        key={index}
                        value={value}
                    >
                        <div className="FeatureFlagInstructionsHeader__option">
                            <div className="FeatureFlagInstructionsHeader__option__icon">
                                <Icon />
                            </div>
                            <div>{value}</div>
                        </div>
                    </Select.Option>
                ))}
            </Select>
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

function CodeInstructions({
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

    return (
        <Card size="small">
            <FeatureFlagInstructionsHeader
                options={options}
                headerPrompt={headerPrompt}
                selectedOptionValue={selectedLanguage || selectedOption.value}
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

const PAYLOAD_OPTIONS = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}integrations/js-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSPayloadSnippet,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}integrations/node-integration${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSPayloadSnippet,
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
