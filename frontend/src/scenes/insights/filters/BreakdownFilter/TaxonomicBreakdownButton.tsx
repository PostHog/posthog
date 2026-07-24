import { useValues } from 'kea'
import { ReactElement, useEffect, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

interface TaxonomicBreakdownButtonProps {
    disabledReason?: ReactElement | string
    disabledReasonInteractive?: boolean
    size?: 'small' | 'medium'
}

export function TaxonomicBreakdownButton({
    disabledReason,
    disabledReasonInteractive,
    size,
}: TaxonomicBreakdownButtonProps): JSX.Element {
    const [open, setOpen] = useState(false)
    // Mounting the taxonomic filter is briefly expensive — it builds a list logic per group type,
    // each kicking off requests. Defer the mount to a post-paint effect so the button's loading
    // state renders on the click itself; otherwise the synchronous mount blocks the first frame and
    // the click reads as unresponsive (a dead click).
    const [opening, setOpening] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    useEffect(() => {
        if (opening) {
            setOpen(true)
            setOpening(false)
        }
    }, [opening])

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall />}
                data-attr="add-breakdown-button"
                loading={opening}
                // Open-only, never toggle: while the filter mounts, rapid follow-up clicks must keep
                // it open rather than flip it shut — toggling on every click is what let users
                // rage-click the picker closed before it had finished opening.
                onClick={() => {
                    if (!open && !opening) {
                        setOpening(true)
                    }
                }}
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
