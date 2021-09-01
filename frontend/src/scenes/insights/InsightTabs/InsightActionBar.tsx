import { Button, Popconfirm } from 'antd'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import React from 'react'
import { FilterType, InsightType } from '~/types'
import { SaveOutlined, ClearOutlined } from '@ant-design/icons'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import useBreakpoint from 'antd/lib/grid/hooks/useBreakpoint'
import { Tooltip } from 'lib/components/Tooltip'

interface Props {
    variant?: 'header' | 'sidebar' // Header view shows labels on some viewports; sidebar always hides them
    filters: FilterType
    annotations?: any[] // TODO: Type properly
    insight?: InsightType
    showReset?: boolean
    onReset?: () => void
}

export function InsightActionBar({
    variant = 'header',
    filters,
    annotations = [],
    insight,
    showReset = true,
    onReset,
}: Props): JSX.Element {
    const { push } = useActions(router)
    const { reportInsightsTabReset } = useActions(eventUsageLogic)
    const screens = useBreakpoint()
    const isSmallScreen = screens.xs || (screens.sm && !screens.md)
    const showButtonLabels = variant === 'header' && !isSmallScreen

    return (
        <div className="insights-tab-actions">
            {showReset && (
                <Popconfirm
                    title="Are you sure? This will clear all filters and any progress will be lost."
                    onConfirm={() => {
                        window.scrollTo({ top: 0 })
                        onReset ? onReset() : push(`/insights?insight=${insight}`)
                        reportInsightsTabReset()
                    }}
                >
                    <Tooltip placement="top" title="Reset all filters">
                        <Button type="link" icon={<ClearOutlined />} className="btn-reset">
                            {showButtonLabels && 'Reset'}
                        </Button>
                    </Tooltip>
                </Popconfirm>
            )}
            <SaveToDashboard
                displayComponent={
                    <Button icon={<SaveOutlined />} className="btn-save">
                        {showButtonLabels && 'Save'}
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
