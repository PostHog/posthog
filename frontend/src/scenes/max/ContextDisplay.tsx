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
        <div className="w-full">
            <div className="flex flex-wrap items-start gap-2 w-full">
                <TaxonomicPopover
                    size="xsmall"
                    type="tertiary"
                    className="-mx-1.5 flex-shrink-0"
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
                    className="flex flex-wrap gap-1 flex-1 min-w-0"
                />
            </div>
        </div>
    )
}
