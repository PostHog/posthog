import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
            title: `Turn the internal and test user filter ${enabled ? 'on' : 'off'} for every existing insight?`,
            width: 560,
            content: (
                <div className="flex flex-col gap-3">
                    <p className="mb-0">
                        Every insight you already have will {enabled ? 'start' : 'stop'} filtering out internal and test
                        users, using the filters you've defined for them. The default for new insights stays as it is.
                    </p>
                    <div>
                        <p className="mb-1">Left as they are:</p>
                        <ul className="list-disc pl-5 mb-0">
                            <li>SQL insights, which have no such filter</li>
                            <li>Insights you can't edit</li>
                        </ul>
                    </div>
                    <p className="mb-0">Dashboards follow their insights, unless a dashboard sets its own override.</p>
                    <LemonBanner type="warning">
                        There's no undo. Running it the other way later would also flip insights that were set
                        differently before.
                    </LemonBanner>
                </div>
            ),
            primaryButton: {
                children: `Turn the filter ${enabled ? 'on' : 'off'}`,
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
