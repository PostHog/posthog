import { Button } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React from 'react'
import { SaveOutlined } from '@ant-design/icons'
import { FilterType } from '~/types'

export interface InsightTitleProps {
    filters: FilterType
    annotations: any[] // TODO: Type properly
}

export function InsightTitle({ annotations, filters }: InsightTitleProps): JSX.Element {
    return (
        <>
            <h3 className="l3" style={{ display: 'flex', alignItems: 'center' }}>
                Unsaved query{' '}
                <SaveToDashboard
                    displayComponent={<Button type="link" size="small" icon={<SaveOutlined />} />}
                    item={{
                        entity: {
                            filters,
                            annotations,
                        },
                    }}
                />
            </h3>
        </>
    )
}
