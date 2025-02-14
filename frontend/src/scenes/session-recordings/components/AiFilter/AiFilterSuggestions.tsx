import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { aiFilterLogic } from './aiFilterLogic'

export function AiFilterSuggestions(): JSX.Element {
    const filterLogic = aiFilterLogic()
    const { setInput } = useActions(filterLogic)

    const suggestions = [
        'Show me recordings of people who visited sign up page in the last 24 hours',
        'Show me recordings of people who are frustrated',
        'Show me recordings of people who are facing bugs',
    ]

    return (
        <div className="flex items-center justify-center flex-wrap gap-x-2 gap-y-1.5 w-[min(48rem,100%)]">
            {suggestions.map((suggestion) => (
                <LemonButton
                    key={suggestion}
                    className="mb-1"
                    type="secondary"
                    size="xsmall"
                    sideIcon={<IconArrowUpRight />}
                    onClick={() => setInput(suggestion)}
                >
                    {suggestion}
                </LemonButton>
            ))}
        </div>
    )
}
