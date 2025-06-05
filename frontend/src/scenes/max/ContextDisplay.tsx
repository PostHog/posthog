import { useActions, useValues } from 'kea'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { maxContextLogic } from 'scenes/max/maxContextLogic'

import { ContextTags } from './ContextTags'

export function ContextDisplay(): JSX.Element {
    const {
        hasData,
        contextInsights,
        contextDashboards,
        contextEvents,
        contextActions,
        useCurrentPageContext,
        contextOptions,
        taxonomicGroupTypes,
        mainTaxonomicGroupType,
    } = useValues(maxContextLogic)
    const {
        removeContextInsight,
        removeContextDashboard,
        removeContextEvent,
        removeContextAction,
        disableCurrentPageContext,
        handleTaxonomicFilterChange,
    } = useActions(maxContextLogic)

    return (
        <div className="w-full mb-2">
            <div className="flex flex-wrap gap-1">
                <TaxonomicPopover
                    size="xsmall"
                    groupType={mainTaxonomicGroupType}
                    groupTypes={taxonomicGroupTypes}
                    onChange={handleTaxonomicFilterChange}
                    placeholder={hasData ? '@' : '@ Add context'}
                    maxContextOptions={contextOptions}
                />
                <ContextTags
                    insights={contextInsights}
                    dashboards={contextDashboards}
                    events={contextEvents}
                    actions={contextActions}
                    useCurrentPageContext={useCurrentPageContext}
                    onRemoveInsight={removeContextInsight}
                    onRemoveDashboard={removeContextDashboard}
                    onRemoveEvent={removeContextEvent}
                    onRemoveAction={removeContextAction}
                    onDisableCurrentPageContext={disableCurrentPageContext}
                />
            </div>
        </div>
    )
}
