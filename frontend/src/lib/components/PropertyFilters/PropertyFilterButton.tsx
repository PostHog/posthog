import { Button } from 'antd'
import { useValues } from 'kea'
import { formatPropertyLabel } from 'lib/utils'
import React from 'react'
import { cohortsModel } from '~/models'
import { PropertyFilter } from '~/types'
import { keyMapping } from '../PropertyKeyInfo'

export interface Props {
    item: PropertyFilter
    onClick?: () => void
}

const PropertyFilterButton: React.FunctionComponent<Props> = ({ item, onClick }: Props) => {
    const { cohorts } = useValues(cohortsModel)

    return (
        <Button type="primary" shape="round" style={{ maxWidth: '75%' }} onClick={onClick}>
            <span style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {formatPropertyLabel(item, cohorts, keyMapping)}
            </span>
        </Button>
    )
}

export default PropertyFilterButton
