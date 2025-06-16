import { IconAtSign } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { maxContextLogic } from 'scenes/max/maxContextLogic'

import { ContextTags } from './ContextTags'

export function ContextDisplay(): JSX.Element {
    const {
        hasData,
        contextInsights,
        contextDashboards,
        useCurrentPageContext,
        contextOptions,
        taxonomicGroupTypes,
        mainTaxonomicGroupType,
    } = useValues(maxContextLogic)
    const { removeContextInsight, removeContextDashboard, disableCurrentPageContext, handleTaxonomicFilterChange } =
        useActions(maxContextLogic)

    return (
        <div className="px-1 pt-1 w-full">
            <div className="flex flex-wrap items-start gap-1 w-full">
                <TaxonomicPopover
                    size="xxsmall"
                    type="tertiary"
                    className="flex-shrink-0 border"
                    groupType={mainTaxonomicGroupType}
                    groupTypes={taxonomicGroupTypes}
                    onChange={handleTaxonomicFilterChange}
                    icon={<IconAtSign />}
                    placeholder={!hasData ? 'Add context' : null}
                    maxContextOptions={contextOptions}
                    width={450}
                />
                <ContextTags
                    insights={contextInsights}
                    dashboards={contextDashboards}
                    useCurrentPageContext={useCurrentPageContext}
                    onRemoveInsight={removeContextInsight}
                    onRemoveDashboard={removeContextDashboard}
                    onDisableCurrentPageContext={disableCurrentPageContext}
                    className="flex flex-wrap gap-1 flex-1 min-w-0"
                />
            </div>
        </div>
    )
}
