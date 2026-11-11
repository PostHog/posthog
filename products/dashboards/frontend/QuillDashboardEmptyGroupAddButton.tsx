import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuTrigger } from '@posthog/quill'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { QuillDashboardAddTileMenuContent } from './QuillDashboardAddTileMenuContent'

export function QuillDashboardEmptyGroupAddButton({ groupKey }: { groupKey: string }): JSX.Element {
    const {
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        setAddTargetTileGroupKey,
    } = useActions(dashboardLogic)

    const options = getDashboardAddTileOptions({
        onAddInsight: openAddInsightModal,
        onAddText: openTextTileModal,
        onAddImage: openImageTileModal,
        onAddButton: openButtonTileModal,
        setAddWidgetModalOpen,
    })

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="primary" data-attr="dashboard-tile-group-empty-tab-add" />}>
                <IconPlus />
                Add
            </DropdownMenuTrigger>
            <QuillDashboardAddTileMenuContent
                options={options}
                align="center"
                onBeforeSelect={() => setAddTargetTileGroupKey(groupKey)}
            />
        </DropdownMenu>
    )
}
