import { Button, Popconfirm, Tooltip } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React from 'react'
import { FilterType, InsightType } from '~/types'
import { SaveOutlined, ClearOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'

interface Props {
    filters: FilterType
    annotations: any[] // TODO: Type properly
    insight?: InsightType
    onReset?: () => void
}

export function InsightActionBar({ filters, annotations, insight, onReset }: Props): JSX.Element {
    const { push } = useActions(router)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)

    return (
        <div className="insights-tab-actions">
            <Popconfirm
                title="Are you sure? This will clear all filters and any progress will be lost."
                onConfirm={() => {
                    window.scrollTo({ top: 0 })
                    onReset ? onReset() : push(`/insights?insight=${insight}`)
                    reportInsightsTabReset()
                }}
            >
                <Tooltip placement="bottom" title="Reset all filters">
                    <Button type="link" icon={<ClearOutlined />} className="btn-reset">
                        {isSmallScreen ? null : 'Reset'}
                    </Button>
                </Tooltip>
            </Popconfirm>
            <SaveToDashboard
                displayComponent={
                    <Button icon={<SaveOutlined />} className="btn-save">
                        {isSmallScreen ? null : 'Save'}
                    </Button>
                }
                tooltipOptions={{
                    placement: 'bottom',
                    title: 'Save to dashboard',
                }}
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
