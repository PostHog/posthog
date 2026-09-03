import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'
import { exactMatchOperatorFor } from 'scenes/web-analytics/common'

import { ProductIntentContext, ProductKey, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'

interface ErrorTrackingButtonProps {
    breakdownBy: WebStatsBreakdown
    value: string
    /** Web analytics can clean paths; error tracking can't, so the operator has to clean both sides. */
    doPathCleaning?: boolean
}

export const ErrorTrackingButton = ({ breakdownBy, value, doPathCleaning }: ErrorTrackingButtonProps): JSX.Element => {
    // Only show for FrustrationMetrics or Page breakdowns
    if (breakdownBy !== WebStatsBreakdown.FrustrationMetrics && breakdownBy !== WebStatsBreakdown.Page) {
        return <></>
    }

    if (!value || value === '') {
        return <></>
    }

    return (
        <LemonButton
            // Both supported breakdowns are built on `$pathname`, so `value` is a bare path such as
            // `/pricing`. Matching it against `$current_url` never hits, as that holds the absolute URL.
            to={urls.errorTracking({
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: '$pathname',
                                    value: [value],
                                    operator: exactMatchOperatorFor(
                                        '$pathname',
                                        PropertyFilterType.Event,
                                        doPathCleaning
                                    ),
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                },
            })}
            icon={<IconWarning />}
            type="tertiary"
            size="xsmall"
            tooltip="View errors for this page"
            className="no-underline"
            targetBlank
            hideExternalLinkIcon={true}
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
                void addProductIntentForCrossSell({
                    from: ProductKey.WEB_ANALYTICS,
                    to: ProductKey.ERROR_TRACKING,
                    intent_context: ProductIntentContext.WEB_ANALYTICS_FRUSTRATING_PAGES,
                })
            }}
        />
    )
}
