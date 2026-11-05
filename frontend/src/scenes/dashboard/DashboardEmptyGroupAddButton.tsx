import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { getAddTileMenuItems } from './DashboardHeaderActions'
import { dashboardLogic } from './dashboardLogic'

export function DashboardEmptyGroupAddButton({ groupKey }: { groupKey: string }): JSX.Element {
    const {
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        setAddTargetTileGroupKey,
    } = useActions(dashboardLogic)

    return (
        <LemonMenu
            items={getAddTileMenuItems({
                onBeforeSelect: () => setAddTargetTileGroupKey(groupKey),
                onAddInsight: openAddInsightModal,
                onAddText: openTextTileModal,
                onAddImage: openImageTileModal,
                onAddButton: openButtonTileModal,
                setAddWidgetModalOpen,
            })}
        >
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlusSmall />}
                data-attr="dashboard-tile-group-empty-tab-add"
            >
                Add
            </LemonButton>
        </LemonMenu>
    )
}
