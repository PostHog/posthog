import { LemonTag } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { PropertyFilterType } from '~/types'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import React, { useState } from 'react'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'

type EditWrapperProps = {
    isViewOnly: boolean
    filterOpen: boolean
    setFilterOpen: (open: boolean) => void
    children: React.ReactNode
}

const EditWrapper = ({ isViewOnly, filterOpen, setFilterOpen, children }: EditWrapperProps): JSX.Element =>
    isViewOnly ? (
        <>{children}</>
    ) : (
        <TaxonomicBreakdownPopover open={filterOpen} setOpen={setFilterOpen}>
            <div>
                {/* :TRICKY: we don't want the close button to be active when the edit popover is open.
                 * Therefore we're wrapping the lemon tag a context provider to override the parent context. */}
                <PopoverReferenceContext.Provider value={null}>{children}</PopoverReferenceContext.Provider>
            </div>
        </TaxonomicBreakdownPopover>
    )

type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: PropertyFilterType
    isTrends: boolean
}

export function BreakdownTag({ breakdown, breakdownType, isTrends }: BreakdownTagProps): JSX.Element {
    const [filterOpen, setFilterOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const logicProps = { breakdown, breakdownType, isTrends }
    const { isViewOnly, shouldShowMenu, propertyName } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <EditWrapper isViewOnly={isViewOnly} filterOpen={filterOpen} setFilterOpen={setFilterOpen}>
                <LemonTag
                    className="taxonomic-breakdown-filter tag-pill"
                    // display remove button only if we can edit and don't have a separate menu
                    closable={!isViewOnly && !shouldShowMenu}
                    onClose={removeBreakdown}
                    onClick={() => {
                        if (!isViewOnly) {
                            setFilterOpen(!filterOpen)
                        }
                    }}
                    popover={{
                        overlay: shouldShowMenu ? <BreakdownTagMenu /> : undefined,
                        closeOnClickInside: false,
                        onVisibilityChange: (visible) => {
                            setMenuOpen(visible)
                        },
                    }}
                >
                    {breakdownType === 'hogql' ? (
                        <HoqQLPropertyInfo value={propertyName as string} />
                    ) : (
                        <PropertyKeyInfo value={propertyName} disablePopover={filterOpen || menuOpen} />
                    )}
                </LemonTag>
            </EditWrapper>
        </BindLogic>
    )
}
