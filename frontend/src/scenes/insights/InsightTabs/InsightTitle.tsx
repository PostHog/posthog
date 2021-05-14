import { Button } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React, { useState } from 'react'
import { SaveOutlined, DashboardOutlined, UndoOutlined } from '@ant-design/icons'
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
            <h3 className="l3" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
                {fromDashboard && (
                    <DashboardOutlined
                        style={{ color: 'var(--warning)', marginRight: 4 }}
                        title="Insight saved on dashboard"
                    />
                )}
                <div style={{ paddingRight: '0.5em' }}>{fromItemName || 'Unsaved query'}</div>
                <div style={{ display: 'flex', alignItems: 'center' }}>
                    <SaveToDashboard
                        displayComponent={
                            <Button type="link" size="small" icon={<SaveOutlined />}>
                                Add to dashboard
                            </Button>
                        }
                        item={{
                            entity: {
                                filters,
                                annotations,
                            },
                        }}
                    />
                    <Button
                        type="link"
                        size="small"
                        icon={<UndoOutlined />}
                        onClick={() => router.actions.push(`/insights?insight=${filters.insight || ''}`)}
                    >
                        Reset
                    </Button>
                </div>
            </h3>
        </>
    )
}
