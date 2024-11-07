import { LemonSelect, Link } from '@posthog/lemon-ui'
import {
    IconAndroidOS,
    IconAppleIOS,
    IconGolang,
    IconJavascript,
    IconNodeJS,
    IconPHP,
    IconPython,
    IconRuby,
} from 'lib/lemon-ui/icons'
import { useState } from 'react'

import { Experiment, MultivariateFlagVariant } from '~/types'

import {
    AndroidSnippet,
    GolangSnippet,
    IOSSnippet,
    JSSnippet,
    NodeJSSnippet,
    PHPSnippet,
    PythonSnippet,
    ReactSnippet,
    RNSnippet,
    RubySnippet,
} from './ExperimentCodeSnippets'

interface ExperimentImplementationDetailsProps {
    experiment: Partial<Experiment> | null
}

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=experiment'
const DOC_BASE_URL = 'https://posthog.com/docs/'
const FF_ANCHOR = '#feature-flags'

export enum LibraryType {
    Client = 'Client',
    Server = 'Server',
}

const OPTIONS = [
    {
        value: 'JavaScript',
        documentationLink: `${DOC_BASE_URL}libraries/js${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: JSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Android',
        documentationLink: `${DOC_BASE_URL}libraries/android${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconAndroidOS,
        Snippet: AndroidSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Go',
        documentationLink: `${DOC_BASE_URL}libraries/go${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconGolang,
        Snippet: GolangSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'iOS',
        documentationLink: `${DOC_BASE_URL}libraries/ios${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconAppleIOS,
        Snippet: IOSSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Node.js',
        documentationLink: `${DOC_BASE_URL}libraries/node${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconNodeJS,
        Snippet: NodeJSSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'PHP',
        documentationLink: `${DOC_BASE_URL}libraries/php${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPHP,
        Snippet: PHPSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'Python',
        documentationLink: `${DOC_BASE_URL}libraries/python${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconPython,
        Snippet: PythonSnippet,
        type: LibraryType.Server,
    },
    {
        value: 'React',
        documentationLink: `${DOC_BASE_URL}libraries/react${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: ReactSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'React Native',
        documentationLink: `${DOC_BASE_URL}libraries/react-native${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconJavascript,
        Snippet: RNSnippet,
        type: LibraryType.Client,
    },
    {
        value: 'Ruby',
        documentationLink: `${DOC_BASE_URL}libraries/ruby${UTM_TAGS}${FF_ANCHOR}`,
        Icon: IconRuby,
        Snippet: RubySnippet,
        type: LibraryType.Server,
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
            options={[
                {
                    title: 'Client libraries',
                    options: OPTIONS.filter((option) => option.type == LibraryType.Client).map(({ Icon, value }) => ({
                        value,
                        label: value,
                        labelInMenu: (
                            <div className="flex items-center space-x-2">
                                <Icon />
                                <span>{value}</span>
                            </div>
                        ),
                    })),
                },
                {
                    title: 'Server libraries',
                    options: OPTIONS.filter((option) => option.type == LibraryType.Server).map(({ Icon, value }) => ({
                        value,
                        label: value,
                        labelInMenu: (
                            <div className="flex items-center space-x-2">
                                <Icon />
                                <span>{value}</span>
                            </div>
                        ),
                    })),
                },
            ]}
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
