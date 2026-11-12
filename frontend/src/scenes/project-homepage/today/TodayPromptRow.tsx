import type { ComponentProps } from 'react'

import { TodayPromptItem } from './TodayPromptItem'

export function TodayPromptRow(props: ComponentProps<typeof TodayPromptItem>): JSX.Element {
    return (
        <ol className="TodayRows">
            <TodayPromptItem {...props} />
        </ol>
    )
}
