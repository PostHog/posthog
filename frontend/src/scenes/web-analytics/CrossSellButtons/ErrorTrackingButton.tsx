import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntentContext, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, ProductKey, PropertyFilterType, PropertyOperator } from '~/types'

interface ErrorTrackingButtonProps {
    breakdownBy: WebStatsBreakdown
    value: string
}

export const ErrorTrackingButton = ({ breakdownBy, value }: ErrorTrackingButtonProps): JSX.Element => {
    // Only show for FrustrationMetrics or Page breakdowns
    if (breakdownBy !== WebStatsBreakdown.FrustrationMetrics && breakdownBy !== WebStatsBreakdown.Page) {
        return <></>
    }

    if (!value || value === '') {
        return <></>
    }

    return (
        <LemonButton
            to={urls.errorTracking({
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    key: '$current_url',
                                    value: [value],
                                    operator: PropertyOperator.Exact,
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
