import { LemonTag, LemonTagProps } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { BreakdownType, GroupTypeIndex } from '~/types'

import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'

type EditableBreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    isTrends: boolean
    size?: 'small' | 'medium'
}

export function EditableBreakdownTag({
    breakdown,
    breakdownType,
    isTrends,
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
                taxanomicType={taxonomicBreakdownType}
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
                                closable={false}
                                onClose={removeBreakdown}
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
                                disablePropertyInfo={filterOpen || menuOpen}
                                size={size}
                            />
                        </PopoverReferenceContext.Provider>
                    </div>
                ) : (
                    <div>
                        {/* If multiple breakdownsa are enabled and it's not a numeric or URL property, enable the delete button */}
                        <BreakdownTag
                            breakdown={breakdown}
                            breakdownType={breakdownType}
                            closable
                            onClose={removeBreakdown}
                            onClick={() => {
                                setFilterOpen(!filterOpen)
                            }}
                            disablePropertyInfo={filterOpen || menuOpen}
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
} & Omit<LemonTagProps, 'children'>

export function BreakdownTag({
    breakdown,
    breakdownType = 'event',
    disablePropertyInfo,
    ...props
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

    return (
        <LemonTag type="breakdown" {...props}>
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
        </LemonTag>
    )
}
