import {
    DndContext,
    DragEndEvent,
    MouseSensor,
    TouchSensor,
    useDraggable,
    useDroppable,
    useSensor,
    useSensors,
} from '@dnd-kit/core'
import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconDashboard, IconFolder } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType } from '~/types'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'
import {
    dashboardDraggableId,
    DashboardFolderGroup,
    folderDroppableId,
    parseDashboardDragEnd,
} from './dashboardsFileSystemUtils'

function DashboardCard({ dashboard }: { dashboard: DashboardBasicType }): JSX.Element {
    // The 10px mouse activation distance (see sensors below) keeps a plain click a navigation and a
    // longer pointer movement a drag.
    const { attributes, listeners, setNodeRef } = useDraggable({ id: dashboardDraggableId(dashboard.id) })
    return (
        <div ref={setNodeRef} {...attributes} {...listeners}>
            <Link to={urls.dashboard(dashboard.id)} data-attr="dashboards-grid-card">
                <LemonCard hoverEffect className="flex flex-col gap-1 h-full">
                    <IconDashboard className="text-2xl text-muted" />
                    <span className="font-semibold truncate">{dashboard.name || 'Untitled'}</span>
                    {dashboard.description ? (
                        <span className="text-xs text-muted truncate">{dashboard.description}</span>
                    ) : null}
                </LemonCard>
            </Link>
        </div>
    )
}

function FolderGroup({ group }: { group: DashboardFolderGroup }): JSX.Element {
    const { collapsedFolders } = useValues(dashboardsFileSystemLogic)
    const { toggleFolder } = useActions(dashboardsFileSystemLogic)
    const { setNodeRef, isOver } = useDroppable({ id: folderDroppableId(group.folder) })
    const collapsed = !!collapsedFolders[group.folder]

    return (
        <div className="flex flex-col gap-2">
            <button
                type="button"
                ref={setNodeRef}
                className={`flex items-center gap-2 text-left font-semibold rounded p-1 ${
                    isOver ? 'ring-2 ring-accent' : ''
                }`}
                onClick={() => toggleFolder(group.folder)}
            >
                {collapsed ? <IconChevronRight /> : <IconChevronDown />}
                <IconFolder className="text-muted" />
                <span>{group.folder}</span>
                <span className="text-muted font-normal">· {group.dashboards.length}</span>
            </button>
            {!collapsed ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
                    {group.dashboards.map((dashboard) => (
                        <DashboardCard key={dashboard.id} dashboard={dashboard} />
                    ))}
                </div>
            ) : null}
        </div>
    )
}

// Grid arm (variant=grid): dashboards as cards grouped under collapsible folder headers, reusing the
// same folder structure the sidebar tree shows. Drag a card onto a folder header to file it (the move
// delegates to projectTreeDataLogic). No drill-in navigation or clipboard — that's the finder arm.
export function DashboardsGrid(): JSX.Element {
    const { dashboardsByFolder } = useValues(dashboardsFileSystemLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { moveDashboardToFolder } = useActions(dashboardsFileSystemLogic)

    const mouseSensor = useSensor(MouseSensor, { activationConstraint: { distance: 10 } })
    const touchSensor = useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } })
    const sensors = useSensors(mouseSensor, touchSensor)

    const onDragEnd = (event: DragEndEvent): void => {
        const move = parseDashboardDragEnd(event.active?.id, event.over?.id)
        if (move) {
            moveDashboardToFolder(move.dashboardId, move.folder)
        }
    }

    if (dashboardsLoading && dashboardsByFolder.length === 0) {
        return <Spinner className="text-2xl" />
    }

    return (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <div className="flex flex-col gap-6" data-attr="dashboards-grid">
                {dashboardsByFolder.map((group) => (
                    <FolderGroup key={group.folder} group={group} />
                ))}
            </div>
        </DndContext>
    )
}
