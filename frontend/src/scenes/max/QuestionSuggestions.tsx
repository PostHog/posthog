import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { maxLogic } from './maxLogic'

export function QuestionSuggestions(): JSX.Element {
    const { askMax } = useActions(maxLogic)

    const suggestions = ['What are my most popular pages?', 'Who are my top users?', 'Which features see most usage?']

    return (
        <div className="flex gap-2 w-[min(40rem,100%)] items-center justify-center">
            {suggestions.map((suggestion, index) => (
                <LemonButton
                    key={index}
                    onClick={() => askMax(suggestion)}
                    size="xsmall"
                    type="secondary"
                    sideIcon={<IconArrowUpRight />}
                >
                    {suggestion}
                </LemonButton>
            ))}
        </div>
    )
}
