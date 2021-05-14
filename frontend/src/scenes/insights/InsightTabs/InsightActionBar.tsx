import { Button, Popconfirm } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React from 'react'
import { FilterType } from '~/types'
import { SaveOutlined, ClearOutlined } from '@ant-design/icons'

interface Props {
    filters: FilterType
    annotations: any[] // TODO: Type properly
    onReset: () => void
}

export function InsightActionBar({ filters, annotations, onReset }: Props): JSX.Element {
    return (
        <div className="insights-tab-actions">
            <Popconfirm
                title="Are you sure? This will clear all filters and any progress will be lost."
                onConfirm={() => {
                    window.scrollTo({ top: 0 })
                    onReset()
                }}
            >
                <Button type="link" icon={<ClearOutlined />} className="btn-reset">
                    Reset all
                </Button>
            </Popconfirm>
            <SaveToDashboard
                displayComponent={
                    <Button icon={<SaveOutlined />} className="btn-save">
                        Save to dashboard
                    </Button>
                }
                item={{
                    entity: {
                        filters,
                        annotations,
                    },
                }}
            />
        </div>
    )
}
