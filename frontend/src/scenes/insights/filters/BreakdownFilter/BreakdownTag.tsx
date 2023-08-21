import { LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { PropertyFilterType } from '~/types'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { useState } from 'react'

type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: PropertyFilterType
    isTrends: boolean
}

export function BreakdownTag({ breakdown, breakdownType, isTrends }: BreakdownTagProps): JSX.Element {
    const [open, setOpen] = useState(false)

    const logicProps = { breakdown, isTrends, breakdownType }
    const { isViewOnly, shouldShowMenu, propertyName } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <TaxonomicBreakdownPopover open={open} setOpen={setOpen}>
                <div>
                    <LemonTag
                        className="taxonomic-breakdown-filter tag-pill"
                        // display remove button only if we can edit and don't have a separate menu
                        closable={!isViewOnly && !shouldShowMenu}
                        onClick={() => {
                            setOpen(!open)
                        }}
                        onClose={removeBreakdown}
                        popover={{
                            overlay: shouldShowMenu ? <BreakdownTagMenu /> : undefined,
                            closeOnClickInside: false,
                        }}
                    >
                        <PropertyKeyInfo value={propertyName} disablePopover={open} />
                    </LemonTag>
                </div>
            </TaxonomicBreakdownPopover>
        </BindLogic>
    )
}
