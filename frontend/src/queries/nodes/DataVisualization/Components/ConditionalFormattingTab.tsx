import { IconLoading } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { conditionalFormattingLogic } from './conditionalFormattingLogic'

export const ConditionalFormattingTab = (): JSX.Element => {
    const { compileHog } = useActions(conditionalFormattingLogic)
    const { hogLoading } = useValues(conditionalFormattingLogic)

    return (
        <div className="flex flex-col w-full">
            <LemonInput
                onBlur={(props) => compileHog({ hog: props.target.value })}
                suffix={hogLoading ? <IconLoading /> : null}
            />
        </div>
    )
}
