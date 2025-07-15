import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'

export function BaseCurrency({ hideTitle = false }: { hideTitle?: boolean }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <div>
            {!hideTitle && <h3>Base currency</h3>}
            <p>
                PostHog will convert all currency values for the entire team to this currency before displaying them to
                you. If we can't properly detect your currency, we'll assume it's in this currency as well.
            </p>
            <CurrencyDropdown
                value={currentTeam?.base_currency || null}
                onChange={(currency: CurrencyCode | null) => {
                    updateCurrentTeam({ base_currency: currency ?? undefined })
                }}
            />
        </div>
    )
}
