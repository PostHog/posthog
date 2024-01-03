import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { useState } from 'react'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

export function TaxonomicBreakdownButton(): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type="secondary"
                icon={<IconPlusMini color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? 'Add cohort'
                    : 'Add breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
