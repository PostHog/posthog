import { BindLogic } from 'kea'
import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, Popover } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { AddIntegrationButton } from './AddIntegrationButton'
import { ConversionGoalFilterButton } from './ConversionGoalFilterButton'
import { ConversionGoalModal } from './ConversionGoalModal'
import { IntegrationFilter } from './IntegrationFilter'

export const MarketingAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const { compareFilter, dateFilter, shouldFilterTestAccounts, optionsOpen } = useValues(marketingAnalyticsLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { setCompareFilter, setDates, updateFilterTestAccounts, setOptionsOpen } = useActions(marketingAnalyticsLogic)
    // The setting lives on the project, so flipping it changes what everyone sees.
    const editRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
            <FilterBar
                top={tabs}
                left={
                    <div className="flex items-center gap-4">
                        <Shortcut
                            name="MarketingAnalyticsRefresh"
                            keybind={[keyBinds.refresh]}
                            intent="Refresh data"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <ReloadAll />
                        </Shortcut>
                        <ConversionGoalFilterButton />
                    </div>
                }
                right={
                    <>
                        <Shortcut
                            name="MarketingAnalyticsAddIntegration"
                            keybind={[keyBinds.new]}
                            intent="Add integration"
                            interaction="click"
                            scope={Scene.MarketingAnalytics}
                        >
                            <AddIntegrationButton />
                        </Shortcut>
                        <Popover
                            visible={optionsOpen}
                            onClickOutside={() => setOptionsOpen(false)}
                            placement="bottom-end"
                            overlay={
                                // Ordered by how often they get touched, so the rarely-changed
                                // project setting sits last.
                                <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
                                    <div>
                                        <div className="text-muted mb-2 text-xs font-semibold uppercase">
                                            Date range
                                        </div>
                                        <DateFilter
                                            allowTimePrecision
                                            dateFrom={dateFilter.dateFrom}
                                            dateTo={dateFilter.dateTo}
                                            onChange={setDates}
                                        />
                                    </div>
                                    <div>
                                        <div className="text-muted mb-2 text-xs font-semibold uppercase">
                                            Comparison
                                        </div>
                                        <CompareFilter
                                            compareFilter={compareFilter}
                                            updateCompareFilter={setCompareFilter}
                                        />
                                    </div>
                                    <div>
                                        <div className="text-muted mb-2 text-xs font-semibold uppercase">
                                            Integrations
                                        </div>
                                        <IntegrationFilter />
                                    </div>
                                    <LemonDivider className="my-0" />
                                    {/* Only the event side honors this: ad spend comes from the platforms. */}
                                    <TestAccountFilterSwitch
                                        fullWidth
                                        checked={shouldFilterTestAccounts}
                                        onChange={updateFilterTestAccounts}
                                        disabledReason={
                                            editRestrictionReason ?? (currentTeamLoading ? 'Saving…' : undefined)
                                        }
                                    />
                                </div>
                            }
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconGear />}
                                onClick={() => setOptionsOpen(!optionsOpen)}
                                data-attr="marketing-analytics-options"
                            >
                                Options
                            </LemonButton>
                        </Popover>
                    </>
                }
            />
            <ConversionGoalModal />
        </BindLogic>
    )
}
