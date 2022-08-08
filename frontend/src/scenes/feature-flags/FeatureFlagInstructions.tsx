import React, { useState } from 'react'

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
} from 'lib/components/icons'
import { LemonDivider } from 'lib/components/LemonDivider'
import {
    APISnippet,
    JSSnippet,
    PythonSnippet,
    NodeJSSnippet,
    PHPSnippet,
    RubySnippet,
    GolangSnippet,
} from 'scenes/feature-flags/FeatureFlagSnippets'

import './FeatureFlagInstructions.scss'

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=feature-flag'
const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'

const OPTIONS = [
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
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
}): JSX.Element {
    return (
        <Row className="FeatureFlagInstructionsHeader" justify="space-between" align="middle">
            <div className="FeatureFlagInstructionsHeader__header-title">
                <IconFlag className="FeatureFlagInstructionsHeader__header-title__icon" />
                <b>Learn how to use feature flags in your code</b>
            </div>

            <Select
                data-attr="feature-flag-instructions-select"
                value={selectedOptionValue}
                style={{ width: 140 }}
                onChange={selectOption}
            >
                {OPTIONS.map(({ value, Icon }, index) => (
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

function FeatureFlagInstructionsFooter({ documenrationLink }: { documenrationLink: string }): JSX.Element {
    return (
        <div className="mt-4">
            Need more information?{' '}
            <a data-attr="feature-flag-doc-link" target="_blank" rel="noopener" href={documenrationLink}>
                Check the docs <IconOpenInNew />
            </a>
        </div>
    )
}

export function FeatureFlagInstructions({ featureFlagKey }: { featureFlagKey: string }): JSX.Element {
    const [defaultSelectedOption] = OPTIONS
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)

    const selectOption = (selectedValue: string): void => {
        const option = OPTIONS.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }
    }

    return (
        <Card size="small">
            <FeatureFlagInstructionsHeader selectedOptionValue={selectedOption.value} selectOption={selectOption} />
            <LemonDivider />
            <div className="mt mb">
                <selectedOption.Snippet data-attr="feature-flag-instructions-snippet" flagKey={featureFlagKey} />
            </div>
            <LemonDivider />
            <FeatureFlagInstructionsFooter documenrationLink={selectedOption.documentationLink} />
        </Card>
    )
}
