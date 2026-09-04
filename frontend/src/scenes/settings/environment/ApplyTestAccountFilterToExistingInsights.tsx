import { useActions, useValues } from 'kea'

import { LemonButton, Link } from '@posthog/lemon-ui'

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
            title: `Turn the internal and test user filter ${enabled ? 'on' : 'off'} for every insight in this project?`,
            width: 560,
            content: (
                <div className="flex flex-col gap-3">
                    <p className="mb-0">
                        Every insight in this project will {enabled ? 'start' : 'stop'} filtering out internal and test
                        users, including insights other people created. This replaces whatever each insight is set to
                        now.
                    </p>
                    <div>
                        <p className="mb-1">Left as they are:</p>
                        <ul className="list-disc pl-5 mb-0">
                            <li>SQL insights, which have no such filter</li>
                            <li>
                                Insights you can't edit. An organization admin can run this to cover those, or you can
                                ask for edit access to them.{' '}
                                <Link to="https://posthog.com/docs/settings/access-control">About access control</Link>
                            </li>
                            <li>
                                Insights saved in an older format. Open and save one to convert it, then run this again.
                            </li>
                        </ul>
                    </div>
                    <p className="mb-0">
                        Dashboards follow their insights, unless a dashboard sets its own override. The default for new
                        insights doesn't change.
                    </p>
                    <LemonBanner type="warning">
                        There's no bulk undo. Running it the other way later would set every insight to{' '}
                        {enabled ? 'off' : 'on'}, not restore what each one had before. To get a single insight back,
                        check its activity log for the previous setting.
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
        <div>
            {/* Sized below the settings section's own h2, so this reads as part of it rather than a sibling. */}
            <h3 className="text-sm font-semibold mb-1">Existing insights</h3>
            <p className="text-secondary text-sm">
                Turn the internal and test user filter on or off for every insight in this project. This doesn't change
                the default for new insights.
            </p>
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
        </div>
    )
}
