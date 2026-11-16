import { LemonSelect } from '@posthog/lemon-ui'

import type { MathOptionChoice } from './types'

export function MathOptionChoiceSelect({ choice }: { choice: MathOptionChoice }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span>{choice.prefix}</span>
            <LemonSelect
                value={choice.value}
                onSelect={(value) => choice.onSelect(value)}
                options={choice.options}
                onClick={(e) => e.stopPropagation()}
                size="small"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="right"
            />
        </div>
    )
}
