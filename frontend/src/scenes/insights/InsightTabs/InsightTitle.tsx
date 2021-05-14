import { Button } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React, { useState } from 'react'
import { SaveOutlined, DashboardOutlined } from '@ant-design/icons'
import { FilterType } from '~/types'
import { router } from 'kea-router'

export interface InsightTitleProps {
    filters: FilterType
    annotations: any[] // TODO: Type properly
}

export function InsightTitle({ annotations, filters }: InsightTitleProps): JSX.Element {
    const [{ fromItemName, fromDashboard }] = useState(router.values.hashParams)
    return (
        <>
            <h3 className="l3" style={{ display: 'flex', alignItems: 'center' }}>
                {fromDashboard && (
                    <DashboardOutlined
                        style={{ color: 'var(--warning)', marginRight: 4 }}
                        title="Insight saved on dashboard"
                    />
                )}
                {fromItemName || 'Unsaved query'}{' '}
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
