import { IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { SuggestionsTurnOffReason } from '../../settings/evalSuggestionsSettingsLogic'

const TURN_OFF_REASONS: { reason: SuggestionsTurnOffReason; label: string }[] = [
    { reason: 'not_useful', label: 'Not useful for this project' },
    { reason: 'write_own_evals', label: 'We write our own evals' },
    { reason: 'not_now', label: 'Not right now' },
]

export function EvaluationSuggestionsTurnOffMenu({
    loading,
    onTurnOff,
}: {
    loading: boolean
    onTurnOff: (reason: SuggestionsTurnOffReason | null) => void
}): JSX.Element {
    return (
        <LemonMenu
            items={[
                {
                    title: 'Why turn off suggested evals?',
                    items: TURN_OFF_REASONS.map(({ reason, label }) => ({ label, onClick: () => onTurnOff(reason) })),
                },
                { items: [{ label: 'Turn off without a reason', onClick: () => onTurnOff(null) }] },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconX />}
                tooltip="Turn off suggested evals"
                loading={loading}
                data-attr="eval-suggestions-turn-off"
            />
        </LemonMenu>
    )
}
