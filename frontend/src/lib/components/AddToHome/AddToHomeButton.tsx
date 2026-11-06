import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { HomePinInsight, homePinsLogic } from './homePinsLogic'

export function AddToHomeButton({ insight }: { insight: HomePinInsight }): JSX.Element {
    const { homePinState } = useValues(homePinsLogic)
    const { toggleHomePin } = useActions(homePinsLogic)
    const { pinned, disabledReason } = homePinState(insight)

    return (
        <LemonButton
            onClick={() => toggleHomePin(insight, 'dashboard_card')}
            disabledReason={disabledReason}
            fullWidth
            data-attr="insight-card-add-to-home"
        >
            {pinned ? 'Remove from home' : 'Add to home'}
        </LemonButton>
    )
}
