import { Button } from 'antd'
import { useValues } from 'kea'
import { formatPropertyLabel } from 'lib/utils'
import React from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import clsx from 'clsx'

export interface Props {
    item: AnyPropertyFilter
    greyBadges?: boolean
    onClick?: () => void
    setRef?: (ref: HTMLElement) => void
}

export function PropertyFilterButton({ item, ...props }: Props): JSX.Element {
    const { cohorts } = useValues(cohortsModel)

    return <FilterButton {...props}>{formatPropertyLabel(item, cohorts, keyMapping)}</FilterButton>
}

interface FilterRowProps {
    greyBadges?: boolean
    onClick?: () => void
    setRef?: (ref: HTMLElement) => void
    children: string | JSX.Element
}

export function FilterButton({ greyBadges, onClick, setRef, children }: FilterRowProps): JSX.Element {
    return (
        <Button
            type="primary"
            shape="round"
            style={{ overflow: 'hidden' }}
            onClick={onClick}
            ref={setRef}
            className={clsx('property-filter', greyBadges && 'property-filter-grey')}
        >
            <span
                className="ph-no-capture property-filter-button-label"
                style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
                {children}
            </span>
        </Button>
    )
}

export default PropertyFilterButton
