import { LemonSelect, Link } from '@posthog/lemon-ui'
import { IconGolang, IconJavascript, IconNodeJS, IconPHP, IconPython, IconRuby } from 'lib/lemon-ui/icons'
import { useState } from 'react'

import { Experiment, MultivariateFlagVariant, SDKKey } from '~/types'

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
const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'

export const OPTIONS = [
    {
        value: 'JavaScript',
        key: SDKKey.JS_WEB,
        documentationLink: `${DOC_BASE_URL}libraries/js${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSSnippet,
    },
    {
        value: 'ReactNative',
        key: SDKKey.REACT_NATIVE,
        documentationLink: `${DOC_BASE_URL}libraries/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: RNSnippet,
    },
    {
        value: 'Node.js',
        key: SDKKey.NODE_JS,
        documentationLink: `${DOC_BASE_URL}libraries/node${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSSnippet,
    },
    {
        value: 'PHP',
        key: SDKKey.PHP,
        documentationLink: `${DOC_BASE_URL}libraries/php${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPHP,
        Snippet: PHPSnippet,
    },
    {
        value: 'Ruby',
        key: SDKKey.RUBY,
        documentationLink: `${DOC_BASE_URL}libraries/ruby${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconRuby,
        Snippet: RubySnippet,
    },
    {
        value: 'Golang',
        key: SDKKey.GO,
        documentationLink: `${DOC_BASE_URL}libraries/go${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconGolang,
        Snippet: GolangSnippet,
    },
    {
        value: 'Python',
        key: SDKKey.PYTHON,
        documentationLink: `${DOC_BASE_URL}libraries/python${UTM_TAGS}${FF_ANCHOR}`,
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
        <div>
            <h2 className="font-semibold text-lg mb-2">Implementation</h2>
            <div className="border rounded bg-bg-light">
                <div className="p-6 space-y-4">
                    <div className="flex justify-between">
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
                            <CodeLanguageSelect
                                selectOption={selectOption}
                                selectedOptionValue={selectedOption.value}
                            />
                        </div>
                    </div>
                    <div>
                        <div className="mb-1">
                            <b>Implement your experiment in code</b>
                        </div>
                        <div className="mb-1">
                            <selectedOption.Snippet
                                variant={currentVariant}
                                flagKey={experiment?.feature_flag?.key ?? ''}
                            />
                        </div>

                        <Link subtle to={selectedOption.documentationLink} target="_blank">
                            See the docs for more implementation information.
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
