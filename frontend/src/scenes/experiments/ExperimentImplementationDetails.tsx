import { LemonSelect, Link } from '@posthog/lemon-ui'
import { IconGolang, IconJavascript, IconNodeJS, IconPHP, IconPython, IconRuby } from 'lib/lemon-ui/icons'
import { useState } from 'react'

import { Experiment, MultivariateFlagVariant } from '~/types'

import {
    GolangSnippet,
    JSSnippet,
    NodeJSSnippet,
    PHPSnippet,
    PythonSnippet,
    RNSnippet,
    RubySnippet,
} from './ExperimentCodeSnippets'

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
        <LemonSelect
            size="small"
            className="min-w-[7.5rem]"
            onSelect={selectOption}
            value={selectedOptionValue}
            options={OPTIONS.map(({ value, Icon }) => ({
                value,
                label: value,
                labelInMenu: (
                    <div className="flex items-center space-x-2">
                        <Icon />
                        <span>{value}</span>
                    </div>
                ),
            }))}
        />
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
        <div className="border rounded bg-bg-light">
            <div className="card-secondary p-4 border-b">Feature flag usage and implementation</div>
            <div className="p-6">
                <div className="flex mb-2 justify-between">
                    <div className="flex items-center">
                        <span className="mr-2">Variant group</span>
                        <LemonSelect
                            size="small"
                            className="min-w-[5rem]"
                            onSelect={setCurrentVariant}
                            value={currentVariant}
                            options={(experiment?.parameters?.feature_flag_variants || []).map(
                                (variant: MultivariateFlagVariant) => ({
                                    value: variant.key,
                                    label: variant.key,
                                })
                            )}
                        />
                    </div>
                    <div>
                        <CodeLanguageSelect selectOption={selectOption} selectedOptionValue={selectedOption.value} />
                    </div>
                </div>
                <b>Implement your experiment in code</b>
                <selectedOption.Snippet variant={currentVariant} flagKey={experiment?.feature_flag?.key ?? ''} />

                <Link subtle to={selectedOption.documentationLink} target="_blank">
                    See the docs for more implementation information.
                </Link>
            </div>
        </div>
    )
}
