import { useValues } from 'kea'
import { ReactElement, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { TaxonomicBreakdownFilterLogicProps, taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

interface TaxonomicBreakdownButtonProps {
    logicProps: TaxonomicBreakdownFilterLogicProps
    disabledReason?: ReactElement | string
    disabledReasonInteractive?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownButton({
    logicProps,
    disabledReason,
    disabledReasonInteractive,
    size,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic(logicProps))

    return (
        <TaxonomicBreakdownPopover logicProps={logicProps} open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={disabledReason}
                disabledReasonInteractive={disabledReasonInteractive}
                size={size}
                // When a disabled reason is set, the docs link is embedded inline in the reason —
                // don't render it twice via tooltipDocLink.
                tooltipDocLink={
                    disabledReason
                        ? undefined
                        : taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                          ? 'https://posthog.com/docs/product-analytics/trends/breakdowns#cohorts-and-breakdowns'
                          : 'https://posthog.com/docs/product-analytics/trends/breakdowns'
                }
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers ? 'Cohort' : 'Breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
