import { useActions, useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'

interface BaseCurrencyProps {
    hideTitle?: boolean
    disabledReason?: string
}

export function BaseCurrency({ hideTitle = false, disabledReason }: BaseCurrencyProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <SceneSection
            title={!hideTitle ? 'Base currency' : undefined}
            description="PostHog will convert all currency values for the entire team to this currency before displaying them to you. If we can't properly detect your currency, we'll assume it's in this currency as well."
        >
            <div>
                <CurrencyDropdown
                    value={currentTeam?.base_currency || null}
                    onChange={(currency: CurrencyCode | null) => {
                        updateCurrentTeam({ base_currency: currency ?? undefined })
                    }}
                    disabledReason={disabledReason}
                />
            </div>
        </SceneSection>
    )
}
