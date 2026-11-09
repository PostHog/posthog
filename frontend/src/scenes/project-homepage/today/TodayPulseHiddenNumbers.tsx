import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { todayHighlightsLogic } from './todayHighlightsLogic'

export function TodayPulseHiddenNumbers({ searching }: { searching: boolean }): JSX.Element | null {
    const { pulseHidden } = useValues(todayHighlightsLogic)
    const { showHiddenPulseNumber } = useActions(todayHighlightsLogic)
    if (searching || pulseHidden.length === 0) {
        return null
    }
    return (
        <>
            <Text size="xs" render={<p />} className="m-0 px-2 pt-2 pb-1 text-muted-foreground">
                Hidden
            </Text>
            <ul className="m-0 flex max-h-40 list-none flex-col overflow-y-auto p-0">
                {pulseHidden.map((hidden) => (
                    <li key={hidden.key}>
                        <Button
                            size="row"
                            left
                            onClick={() => showHiddenPulseNumber(hidden)}
                            className="w-full"
                            data-attr="today-pulse-show-hidden"
                        >
                            <span className="min-w-0 flex-1 truncate text-left text-muted-foreground">
                                {hidden.name}
                            </span>
                            <span className="shrink-0 text-xs">Show</span>
                        </Button>
                    </li>
                ))}
            </ul>
        </>
    )
}
