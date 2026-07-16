import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { DashboardLayoutCompactType } from '~/types'

import { dashboardLogic } from './dashboardLogic'

export function DashboardCompactionControl(): JSX.Element | null {
    const { currentLayoutSize, layoutCompactType } = useValues(dashboardLogic)
    const { setLayoutCompactType } = useActions(dashboardLogic)
    const layoutCompactionEnabled = useFeatureFlag('PRODUCT_ANALYTICS_DASHBOARD_LAYOUT_COMPACTION')

    if (!layoutCompactionEnabled || currentLayoutSize === 'xs') {
        return null
    }

    return (
        <div className="hidden items-center gap-2 text-sm text-muted md:flex">
            <span>Compaction</span>
            <LemonSelect<DashboardLayoutCompactType>
                size="small"
                value={layoutCompactType}
                onChange={setLayoutCompactType}
                options={[
                    { value: 'vertical', label: 'Vertical' },
                    { value: 'horizontal', label: 'Horizontal' },
                    { value: 'wrap', label: 'Wrap' },
                    { value: 'none', label: 'None' },
                ]}
                tooltip="Choose how tiles close gaps in the dashboard layout"
            />
        </div>
    )
}
