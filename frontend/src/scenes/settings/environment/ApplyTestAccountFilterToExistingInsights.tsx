import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

import { applyTestAccountFilterLogic } from './applyTestAccountFilterLogic'

export function ApplyTestAccountFilterToExistingInsights(): JSX.Element {
    const { applyToExistingInsights } = useActions(applyTestAccountFilterLogic)
    const { pendingEnabled, bulkSetResponseLoading } = useValues(applyTestAccountFilterLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const noFiltersReason = currentTeam?.test_account_filters?.length ? null : 'Add at least one filter above first'
    const inFlightReason = bulkSetResponseLoading ? 'Applying your last change' : null

    const confirm = (enabled: boolean): void => {
        LemonDialog.open({
            title: `Turn this filter ${enabled ? 'on' : 'off'} for every existing insight?`,
            description: (
                <>
                    This changes the insights you already have. It doesn't change the default for new insights. SQL
                    insights have no such filter, so they stay as they are, and so do insights you can't edit.
                    Dashboards follow their insights unless a dashboard sets its own override.
                    <br />
                    <br />
                    There's no undo. Running it the other way later would also flip insights that were set differently
                    before.
                </>
            ),
            primaryButton: {
                children: `Turn it ${enabled ? 'on' : 'off'}`,
                onClick: () => applyToExistingInsights(enabled),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="flex gap-2">
            {[true, false].map((enabled) => (
                <LemonButton
                    key={String(enabled)}
                    type="secondary"
                    size="small"
                    data-attr={`apply-test-account-filter-to-existing-insights-${enabled ? 'on' : 'off'}`}
                    loading={bulkSetResponseLoading && pendingEnabled === enabled}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason ?? noFiltersReason ?? inFlightReason}
                    onClick={() => confirm(enabled)}
                >
                    {enabled ? 'Turn on for existing insights' : 'Turn off for existing insights'}
                </LemonButton>
            ))}
        </div>
    )
}
