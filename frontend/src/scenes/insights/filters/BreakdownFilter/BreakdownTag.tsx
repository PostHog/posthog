import './BreakdownTag.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconX } from '@posthog/icons'
import { LemonButton, LemonButtonDropdown, LemonButtonWithDropdown } from '@posthog/lemon-ui'

import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { BreakdownType, GroupTypeIndex } from '~/types'

import { BreakdownTagMenu } from './BreakdownTagMenu'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { breakdownTagLogic } from './breakdownTagLogic'
import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'

type EditableBreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    isTrends: boolean
    disablePropertyInfo?: boolean
    size?: 'small' | 'medium'
}

export function EditableBreakdownTag({
    breakdown,
    breakdownType,
    isTrends,
    disablePropertyInfo,
    size = 'medium',
}: EditableBreakdownTagProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const [filterOpen, setFilterOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const logicProps = { insightProps, breakdown, breakdownType, isTrends }
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))
    const { isMultipleBreakdownsEnabled, isHistogramable, isNormalizeable, taxonomicBreakdownType } = useValues(
        breakdownTagLogic(logicProps)
    )

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <TaxonomicBreakdownPopover
                open={filterOpen}
                setOpen={setFilterOpen}
                breakdownValue={breakdown}
                breakdownType={breakdownType}
                taxonomicType={taxonomicBreakdownType}
            >
                {!isMultipleBreakdownsEnabled || isHistogramable || isNormalizeable ? (
                    <div>
                        {/* :TRICKY: we don't want the close button to be active when the edit popover is open.
                         * Therefore we're wrapping the lemon tag a context provider to override the parent context. */}
                        <PopoverReferenceContext.Provider value={null}>
                            <BreakdownTag
                                breakdown={breakdown}
                                breakdownType={breakdownType}
                                // display remove button only if we can edit and don't have a separate menu
                                onClick={() => {
                                    setFilterOpen(!filterOpen)
                                }}
                                popover={{
                                    overlay: <BreakdownTagMenu />,
                                    closeOnClickInside: false,
                                    onVisibilityChange: (visible) => {
                                        setMenuOpen(visible)
                                    },
                                }}
                                disablePropertyInfo={disablePropertyInfo || filterOpen || menuOpen}
                                size={size}
                            />
                        </PopoverReferenceContext.Provider>
                    </div>
                ) : (
                    <div>
                        {/* If multiple breakdowns are enabled and it's not a numeric or URL property, enable the delete button */}
                        <BreakdownTag
                            breakdown={breakdown}
                            breakdownType={breakdownType}
                            onClose={removeBreakdown}
                            onClick={() => {
                                setFilterOpen(!filterOpen)
                            }}
                            disablePropertyInfo={disablePropertyInfo || filterOpen || menuOpen}
                            size={size}
                        />
                    </div>
                )}
            </TaxonomicBreakdownPopover>
        </BindLogic>
    )
}

type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType | null | undefined
    disablePropertyInfo?: boolean
    onClose?: () => void
    onClick?: (e: React.MouseEvent<HTMLDivElement | HTMLButtonElement>) => void
    popover?: LemonButtonDropdown
    size?: 'small' | 'medium'
}

export function BreakdownTag({
    breakdown,
    breakdownType = 'event',
    disablePropertyInfo,
    onClose,
    onClick,
    popover,
    size = 'medium',
}: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { groupTypes } = useValues(groupsModel)

    let propertyName = breakdown

    if (isAllCohort(breakdown)) {
        propertyName = 'All Users'
    } else if (isCohort(breakdown)) {
        propertyName = cohortsById[breakdown]?.name || `Cohort ${breakdown}`
    } else if (breakdownType === 'event_metadata' && (propertyName as string).startsWith('$group_')) {
        const group = groupTypes.get(
            parseInt((propertyName as string).replace('$group_', '')) as unknown as GroupTypeIndex
        )
        if (group) {
            propertyName = group.name_singular || group.group_type
        }
    } else {
        propertyName = extractExpressionComment(propertyName as string)
    }

    const clickable = onClick !== undefined
    const closeable = onClose !== undefined
    const ButtonComponent = clickable ? 'button' : 'div'

    return (
        <ButtonComponent
            className={clsx('BreakdownTag', `BreakdownTag--${size}`, {
                'BreakdownTag--clickable': clickable,
            })}
            type={ButtonComponent === 'button' ? 'button' : undefined}
            onClick={onClick}
        >
            {breakdownType === 'hogql' ? (
                <HoqQLPropertyInfo value={propertyName as string} />
            ) : (
                <PropertyKeyInfo
                    value={propertyName as string}
                    disablePopover={disablePropertyInfo}
                    type={
                        breakdownType
                            ? PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType]
                            : TaxonomicFilterGroupType.EventProperties
                    }
                />
            )}
            {popover?.overlay && (
                <LemonButtonWithDropdown
                    size="xsmall"
                    icon={<IconEllipsis />}
                    onClick={(e) => {
                        e.stopPropagation()
                    }}
                    dropdown={popover}
                    className="p-0.5"
                />
            )}

            {closeable && (
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={(e) => {
                        e.stopPropagation()
                        onClose()
                    }}
                    className="p-0.5"
                />
            )}
        </ButtonComponent>
    )
}
