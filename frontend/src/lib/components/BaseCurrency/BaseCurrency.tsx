import { useActions, useValues } from 'kea'

import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { CurrencyCode } from '~/queries/schema/schema-general'

import { RestrictionScope, useRestrictedArea } from '../RestrictedArea'
import { CurrencyDropdown } from './CurrencyDropdown'
import { QuillCurrencyDropdown } from './QuillCurrencyDropdown'

const BASE_CURRENCY_DESCRIPTION =
    "PostHog will convert all currency values for the entire team to this currency before displaying them to you. If we can't properly detect your currency, we'll assume it's in this currency as well."

interface BaseCurrencyProps {
    hideTitle?: boolean
    disabledReason?: string
}

export function BaseCurrency({ hideTitle = false, disabledReason }: BaseCurrencyProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (currency: CurrencyCode | null): void => {
        updateCurrentTeam({ base_currency: currency ?? undefined })
    }

    if (todayRailNav) {
        const dropdown = (
            <QuillCurrencyDropdown
                value={currentTeam?.base_currency || null}
                onChange={handleChange}
                disabledReason={disabledReason ?? restrictedReason ?? undefined}
            />
        )

        // With the title hidden, the caller already shows the title and description around this setting.
        return hideTitle ? (
            dropdown
        ) : (
            <SceneSection title="Base currency" description={BASE_CURRENCY_DESCRIPTION}>
                {dropdown}
            </SceneSection>
        )
    }

    return (
        <SceneSection title={!hideTitle ? 'Base currency' : undefined} description={BASE_CURRENCY_DESCRIPTION}>
            <div>
                <CurrencyDropdown
                    value={currentTeam?.base_currency || null}
                    onChange={handleChange}
                    disabledReason={disabledReason ?? restrictedReason ?? undefined}
                />
            </div>
        </SceneSection>
    )
}
