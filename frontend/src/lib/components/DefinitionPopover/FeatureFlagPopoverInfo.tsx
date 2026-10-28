import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { DefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopover'
import { pluralize } from 'lib/utils/strings'

import { featureFlagFilterSummaryLogic } from 'products/feature_flags/frontend/featureFlagFilterSummaryLogic'

export function FeatureFlagPopoverInfo({ flagKey }: { flagKey: string }): JSX.Element | null {
    const { summary, flagLoading } = useValues(featureFlagFilterSummaryLogic({ flagKey }))

    if (flagLoading) {
        return <Spinner />
    }
    if (!summary) {
        return null
    }

    return (
        <DefinitionPopover.Grid cols={1}>
            <DefinitionPopover.Card
                title="Status"
                value={summary.archived ? 'Archived' : summary.active ? 'Enabled' : 'Disabled'}
            />
            {summary.conditionCount !== null && (
                <DefinitionPopover.Card
                    title="Release conditions"
                    value={pluralize(summary.conditionCount, 'condition', 'conditions')}
                />
            )}
            {summary.variants && (
                <DefinitionPopover.Card
                    title="Variants"
                    value={
                        summary.variants.length > 0
                            ? summary.variants
                                  .map((variant) => `${variant.key} (${variant.rollout_percentage}%)`)
                                  .join(', ')
                            : 'None (true or false)'
                    }
                />
            )}
        </DefinitionPopover.Grid>
    )
}
