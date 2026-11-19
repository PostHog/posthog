import { IconEllipsis, IconExpand45, IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useDisplay } from '../editor/display'
import { DashboardV2PanelChart, type DashboardV2PanelChartProps } from './DashboardV2PanelChart'

interface DashboardV2PanelProps extends DashboardV2PanelChartProps {
    sample?: boolean
    id?: string
    onView?: () => void
    onEdit?: () => void
    onDuplicate?: () => void
    onRemove?: () => void
}

export function DashboardV2Panel({
    sample,
    id,
    onView,
    onEdit,
    onDuplicate,
    onRemove,
    ...chart
}: DashboardV2PanelProps): JSX.Element {
    const { panel } = chart
    const spacious = useDisplay() === 'spacious'
    const isText = panel.viz.type === 'text'
    const description = panel.description?.trim()
    const descriptionMode = description ? (panel.descriptionMode ?? (spacious ? 'below' : 'info')) : 'hidden'
    const showHeader = !!panel.title || !isText || descriptionMode !== 'hidden'
    const showBadge = !!sample && !isText
    const actions =
        onView || onEdit || onDuplicate || onRemove ? (
            <div
                className="flex items-center gap-1 opacity-0 transition-opacity group-hover/card:opacity-100 focus-within:opacity-100 has-[[data-popup-open]]:opacity-100 motion-reduce:transition-none"
                data-attr="dashboard-v2-panel-actions"
            >
                {onView && (
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label="Expand panel"
                        tooltip="Expand panel"
                        onClick={onView}
                        data-attr="dashboard-v2-panel-expand"
                    >
                        <IconExpand45 />
                    </Button>
                )}
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="default"
                                size="icon-xs"
                                aria-label="Panel menu"
                                data-attr="dashboard-v2-panel-menu"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {onView && (
                            <DropdownMenuItem onClick={onView} data-attr="dashboard-v2-panel-menu-view">
                                View
                            </DropdownMenuItem>
                        )}
                        {onEdit && (
                            <DropdownMenuItem onClick={onEdit} data-attr="dashboard-v2-panel-menu-edit">
                                Edit
                            </DropdownMenuItem>
                        )}
                        {onDuplicate && (
                            <DropdownMenuItem onClick={onDuplicate} data-attr="dashboard-v2-panel-menu-duplicate">
                                Duplicate
                            </DropdownMenuItem>
                        )}
                        {onRemove && (
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={onRemove}
                                data-attr="dashboard-v2-panel-menu-remove"
                            >
                                Remove
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        ) : null

    return (
        <Card
            size={spacious ? 'default' : 'sm'}
            className={`relative isolate h-full min-h-32 overflow-hidden has-[[data-panel-bg]]:text-white ${spacious ? 'rounded-xl shadow-sm' : ''}`}
            data-attr="dashboard-v2-panel"
            data-panel={id}
        >
            {showHeader && (
                <CardHeader className={spacious ? 'border-b-0 pb-0' : undefined}>
                    <CardTitle
                        className={`flex min-w-0 items-center gap-1 ${spacious ? 'text-base font-semibold' : ''}`}
                    >
                        <span className="truncate">{panel.title || 'Untitled panel'}</span>
                        {descriptionMode === 'info' && (
                            <Button
                                variant="link-muted"
                                size="icon-xs"
                                aria-label="Description"
                                tooltip={description}
                                data-attr="dashboard-v2-panel-description"
                            >
                                <IconInfo />
                            </Button>
                        )}
                    </CardTitle>
                    {descriptionMode === 'below' && (
                        <CardDescription className="line-clamp-2">{description}</CardDescription>
                    )}
                    {(showBadge || actions) && (
                        <CardAction className="flex items-center gap-1">
                            {showBadge && <Badge>Sample data</Badge>}
                            {actions}
                        </CardAction>
                    )}
                </CardHeader>
            )}
            {!showHeader && actions && <div className="absolute end-1 top-1 z-10 rounded-md bg-card">{actions}</div>}
            <CardContent className="flex min-h-0 flex-1 flex-col">
                <DashboardV2PanelChart {...chart} />
            </CardContent>
        </Card>
    )
}
