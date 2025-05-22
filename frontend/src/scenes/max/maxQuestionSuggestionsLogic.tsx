import { IconBook, IconGraph, IconHogQL, IconPlug, IconRewindPlay } from '@posthog/icons'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { urls } from 'scenes/urls'

import { productUrls } from '~/products'

import { maxLogic } from './maxLogic'
import type { maxQuestionSuggestionsLogicType } from './maxQuestionSuggestionsLogicType'

export const maxQuestionSuggestionsLogic = kea<maxQuestionSuggestionsLogicType>([
    path(['scenes', 'max', 'questionSuggestionsLogic']),
    connect(() => ({
        values: [maxLogic, ['question']],
        actions: [maxLogic, ['setQuestion', 'focusInput', 'askMax']],
    })),
    actions({
        setActiveGroup: (index: number | null) => ({ index }),
    }),
    reducers({
        activeSuggestionGroupIndex: [
            null as number | null,
            {
                setActiveGroup: (_, { index }) => index,
            },
        ],
    }),
    selectors({
        suggestionGroups: [
            () => [], // Kea selector typing hint
            (): SuggestionGroup[] => QUESTION_SUGGESTIONS_DATA,
        ],

        activeSuggestionGroup: [
            (s) => [s.activeSuggestionGroupIndex, s.suggestionGroups],
            (index, groups): SuggestionGroup | undefined => {
                if (index === null) {
                    return undefined
                }
                return groups[index]
            },
        ],
    }),
])

export interface SuggestionItem {
    label: string
    // In case the actual question to Max is different from the label
    content?: string
}

export interface SuggestionGroup {
    label: string
    icon: JSX.Element
    suggestions: SuggestionItem[]
    url?: string
    tooltip?: string
}

export const QUESTION_SUGGESTIONS_DATA: SuggestionGroup[] = [
    {
        label: 'SQL',
        icon: <IconHogQL />,
        suggestions: [
            {
                label: 'Generate an SQL query to',
                content: 'Generate an SQL query to ',
            },
        ],
        url: urls.sqlEditor(),
        tooltip: 'Max can generate SQL queries using your PostHog data and the data warehouse.',
    },
    {
        label: 'Product Analytics',
        icon: <IconGraph />,
        suggestions: [
            {
                label: 'Create a funnel of the Pirate Metrics (AARRR)',
            },
            {
                label: 'What are the most popular pages or screens?',
            },
            {
                label: 'What is the retention in the last two weeks?',
            },
            {
                label: 'What are the top referring domains?',
            },
            {
                label: 'Calculate a conversion rate for <events or features>',
                content: 'Calculate a conversion rate for ',
            },
        ],
        tooltip: 'Max can generate insights from natural language and tweak existing ones.',
    },
    {
        label: 'Docs',
        icon: <IconBook />,
        suggestions: [
            {
                label: 'How can I create a feature flag?',
            },
            {
                label: 'Where do I watch session replays?',
            },
            {
                label: 'Help me set up an experiment',
            },
            {
                label: 'Explain autocapture',
            },
            {
                label: 'How can I capture an exception?',
            },
        ],
        tooltip: 'Max can help you find the right documentation pieces.',
    },
    {
        label: 'Set up',
        icon: <IconPlug />,
        suggestions: [
            {
                label: 'How can I set up the session replay in <a framework or language>',
                content: 'How can I set up the session replay in ',
            },
            {
                label: 'How can I set up the feature flags in...',
                content: 'How can I set up the feature flags in ',
            },
            {
                label: 'How can I set up the experiments in...',
                content: 'How can I set up the experiments in ',
            },
            {
                label: 'How can I set up the data warehouse in...',
                content: 'How can I set up the data warehouse in ',
            },
            {
                label: 'How can I set up the error tracking in...',
                content: 'How can I set up the error tracking in ',
            },
            {
                label: 'How can I set up the LLM Observability in...',
                content: 'How can I set up the LLM Observability in',
            },
            {
                label: 'How can I set up the product analytics in...',
                content: 'How can I set up the product analytics in',
            },
        ],
        tooltip: 'Max can help you set up PostHog SDKs in your stack.',
    },
    {
        label: 'Session Replay',
        icon: <IconRewindPlay />,
        suggestions: [
            {
                label: 'Find recordings for <description>',
                content: 'Find recordings for ',
            },
        ],
        url: productUrls.replay(),
        tooltip: 'Max can find session recordings for you.',
    },
] as const
