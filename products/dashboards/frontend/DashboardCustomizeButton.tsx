import { IconGridMasonry } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { QuillDashboardCustomizeButton } from './QuillDashboardCustomizeButton'

export function DashboardCustomizeButton(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillDashboardCustomizeButton />
    }

    return (
        <LemonMenu
            items={[{ label: () => <DashboardCustomizeMenu /> }]}
            closeOnClickInside={false}
            placement="bottom-end"
        >
            <LemonButton
                type="secondary"
                data-attr="dashboard-edit-layout-customize-dropdown"
                size="small"
                icon={<IconGridMasonry fontSize="16" />}
            >
                Customize
            </LemonButton>
        </LemonMenu>
    )
}
