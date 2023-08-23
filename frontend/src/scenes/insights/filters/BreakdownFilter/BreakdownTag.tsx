import { useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'

import { LemonTag, LemonTagProps } from '@posthog/lemon-ui'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { BreakdownType } from '~/types'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'

type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    isTrends: boolean
}

export function BreakdownTag({ breakdown, breakdownType, isTrends }: BreakdownTagProps): JSX.Element {
    const [filterOpen, setFilterOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const logicProps = { breakdown, breakdownType, isTrends }
    const { shouldShowMenu } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <TaxonomicBreakdownPopover open={filterOpen} setOpen={setFilterOpen}>
                <div>
                    {/* :TRICKY: we don't want the close button to be active when the edit popover is open.
                     * Therefore we're wrapping the lemon tag a context provider to override the parent context. */}
                    <PopoverReferenceContext.Provider value={null}>
                        <BreakdownTagComponent
                            breakdown={breakdown}
                            breakdownType={breakdownType}
                            // display remove button only if we can edit and don't have a separate menu
                            closable={!shouldShowMenu}
                            onClose={removeBreakdown}
                            onClick={() => {
                                setFilterOpen(!filterOpen)
                            }}
                            popover={{
                                overlay: shouldShowMenu ? <BreakdownTagMenu /> : undefined,
                                closeOnClickInside: false,
                                onVisibilityChange: (visible) => {
                                    setMenuOpen(visible)
                                },
                            }}
                            disablePropertyInfo={filterOpen || menuOpen}
                        />
                    </PopoverReferenceContext.Provider>
                </div>
            </TaxonomicBreakdownPopover>
        </BindLogic>
    )
}

type BreakdownTagComponentProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    disablePropertyInfo?: boolean
} & Omit<LemonTagProps, 'children'>

export function BreakdownTagComponent({
    breakdown,
    breakdownType,
    disablePropertyInfo,
    ...props
}: BreakdownTagComponentProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)

    let propertyName = breakdown

    if (isAllCohort(breakdown)) {
        propertyName = 'All Users'
    } else if (isCohort(breakdown)) {
        propertyName = cohortsById[breakdown]?.name || `Cohort ${breakdown}`
    }

    return (
        <LemonTag className="taxonomic-breakdown-filter tag-pill" {...props}>
            {breakdownType === 'hogql' ? (
                <HoqQLPropertyInfo value={propertyName as string} />
            ) : (
                <PropertyKeyInfo value={propertyName as string} disablePopover={disablePropertyInfo} />
            )}
        </LemonTag>
    )
}
