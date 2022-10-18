import { Card, Select } from 'antd'
import {
    IconGolang,
    IconJavascript,
    IconNodeJS,
    IconOpenInNew,
    IconPHP,
    IconPython,
    IconRuby,
} from 'lib/components/icons'
import { useState } from 'react'
import { Experiment, MultivariateFlagVariant } from '~/types'
import { CaretDownOutlined } from '@ant-design/icons'
import {
    GolangSnippet,
    JSSnippet,
    NodeJSSnippet,
    PHPSnippet,
    PythonSnippet,
    RNSnippet,
    RubySnippet,
} from './ExperimentCodeSnippets'
import { Link } from '@posthog/lemon-ui'

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
}

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=experiment'
const DOC_BASE_URL = 'https://posthog.com/docs/integrate/'
const FF_ANCHOR = '#feature-flags'

const OPTIONS = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}client/js${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSSnippet,
    },
    {
        value: 'ReactNative',
        documentationLink: `${DOC_BASE_URL}client/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: RNSnippet,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}server/node${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSSnippet,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}server/php${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPHP,
        Snippet: PHPSnippet,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}server/ruby${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconRuby,
        Snippet: RubySnippet,
    },
    {
        value: 'Golang',
        documentationLink: `${DOC_BASE_URL}server/go${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconGolang,
        Snippet: GolangSnippet,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}server/python${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPython,
        Snippet: PythonSnippet,
    },
]

export function CodeLanguageSelect({
    selectedOptionValue,
    selectOption,
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
}): JSX.Element {
    return (
        <Select
            value={selectedOptionValue}
            onChange={selectOption}
            style={{ minWidth: 120 }}
            suffixIcon={<CaretDownOutlined />}
        >
            {OPTIONS.map(({ value, Icon }, index) => (
                <Select.Option data-attr={'experiment-instructions-select-option-' + value} key={index} value={value}>
                    <div className="flex items-center">
                        <Icon className="mr-1" /> {value}
                    </div>
                </Select.Option>
            ))}
        </Select>
    )
}

export function ExperimentImplementationDetails({ experiment }: ExperimentImplementationDetailsProps): JSX.Element {
    const defaultVariant = experiment?.parameters?.feature_flag_variants?.[1]?.key ?? 'test'
    const [currentVariant, setCurrentVariant] = useState(defaultVariant)
    const [defaultSelectedOption] = OPTIONS
    const [selectedOption, setSelectedOption] = useState(defaultSelectedOption)

    const selectOption = (selectedValue: string): void => {
        const option = OPTIONS.find((option) => option.value === selectedValue)

        if (option) {
            setSelectedOption(option)
        }
    }

    return (
        <Card
            title={<span className="card-secondary">Feature flag usage and implementation</span>}
            className="experiment-implementation-details"
        >
            <div style={{ justifyContent: 'space-between' }} className="flex mb-2">
                <div>
                    <span className="mr-2">Variant group</span>
                    <Select
                        onChange={setCurrentVariant}
                        value={currentVariant}
                        style={{ minWidth: 80 }}
                        suffixIcon={<CaretDownOutlined />}
                    >
                        {experiment?.parameters?.feature_flag_variants?.map(
                            (variant: MultivariateFlagVariant, idx: number) => (
                                <Select.Option key={idx} value={variant.key}>
                                    {variant.key}
                                </Select.Option>
                            )
                        )}
                    </Select>
                </div>
                <div>
                    <CodeLanguageSelect selectOption={selectOption} selectedOptionValue={selectedOption.value} />
                </div>
            </div>
            <b>Implement your experiment in code</b>
            <selectedOption.Snippet variant={currentVariant} flagKey={experiment?.feature_flag_key ?? ''} />

            <Link to={selectedOption.documentationLink} target="_blank">
                <div className="flex items-center">
                    See the docs for more implementation information. <IconOpenInNew className="ml-1" />
                </div>
            </Link>
        </Card>
    )
}
