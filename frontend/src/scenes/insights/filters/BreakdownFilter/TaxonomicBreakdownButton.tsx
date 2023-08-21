import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useState } from 'react'
import { useValues } from 'kea'
import { LemonButton } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/lemon-ui/icons'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'

export function TaxonomicBreakdownButton(): JSX.Element {
    const [open, setOpen] = useState(false)

    const { taxonomicBreakdownType } = useValues(taxonomicBreakdownFilterLogic)

    return (
        <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
            <LemonButton
                type={'secondary'}
                icon={<IconPlusMini color="var(--primary)" />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                className="taxonomic-breakdown-filter tag-button"
                sideIcon={null}
            >
                {taxonomicBreakdownType === TaxonomicFilterGroupType.CohortsWithAllUsers
                    ? 'Add cohort'
                    : 'Add breakdown'}
            </LemonButton>
        </TaxonomicBreakdownPopover>
    )
}
