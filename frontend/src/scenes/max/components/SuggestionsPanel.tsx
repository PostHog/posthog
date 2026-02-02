import { useActions } from 'kea'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'

import { maxLogic } from '../maxLogic'
import { maxThreadLogic } from '../maxThreadLogic'
import { checkSuggestionRequiresUserInput, stripSuggestionPlaceholders } from '../utils'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

interface SuggestionCategory {
    label: string
    suggestions: { content: string }[]
}

const SUGGESTION_CATEGORIES: SuggestionCategory[] = [
    {
        label: 'Data analysis',
        suggestions: [
            { content: 'What are my top conversion paths?' },
            { content: 'Show me weekly active users trend' },
        ],
    },
    {
        label: 'User behavior',
        suggestions: [
            { content: 'Where are my users struggling in my onboarding?' },
            { content: 'Show me rage clicks from this week' },
        ],
    },
    {
        label: 'Retention',
        suggestions: [
            { content: 'What is my retention rate?' },
            { content: 'Show me retention by country' },
        ],
    },
]

export function SuggestionsPanel(): JSX.Element {
    const { setQuestion, focusInput } = useActions(maxLogic)
    const { askMax } = useActions(maxThreadLogic)

    const handleSuggestionClick = (suggestion: { content: string }): void => {
        if (checkSuggestionRequiresUserInput(suggestion.content)) {
            setQuestion(stripSuggestionPlaceholders(suggestion.content))
            focusInput()
        } else {
            setQuestion(suggestion.content)
            askMax(suggestion.content)
        }
    }

    return (
        <ScrollableShadows direction="vertical" className="flex flex-col" innerClassName="flex flex-col px-2 pt-2 pb-8">
            <div className="flex flex-col gap-1 w-full pb-10">
                {SUGGESTION_CATEGORIES.map((category) => (
                    <div key={category.label} className="flex flex-col gap-1">
                        <Label intent="menu">{category.label}</Label>
                        <ul className="flex flex-col gap-px">
                            {category.suggestions.map((suggestion) => (
                                <Link
                                    to={urls.ai(suggestion.content)}
                                    key={suggestion.content}
                                    className="text-left text-sm px-2 py-1.5 rounded"
                                    onClick={(e) => {
                                        e.preventDefault()
                                        handleSuggestionClick(suggestion)
                                    }}
                                    buttonProps={{
                                        fullWidth: true,
                                    }}
                                >
                                    <span className="truncate">{suggestion.content}</span>
                                </Link>
                            ))}
                        </ul>
                    </div>
                ))}
            </div>
        </ScrollableShadows>
    )
}
