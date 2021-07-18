import { Button } from 'antd'
import { useValues } from 'kea'
import { formatPropertyLabel } from 'lib/utils'
import React from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'

export interface Props {
    item: AnyPropertyFilter
    onClick?: () => void
    setRef?: (ref: HTMLElement) => void
}

export function PropertyFilterButton({ item, onClick, setRef }: Props): JSX.Element {
    const { cohorts } = useValues(cohortsModel)

    return (
        <Button type="primary" shape="round" style={{ maxWidth: '75%' }} onClick={onClick} ref={setRef}>
            <span
                className="ph-no-capture property-filter-button-label"
                style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}
            >
                {formatPropertyLabel(item, cohorts, keyMapping)}
            </span>
        </Button>
    )
}

export default PropertyFilterButton
