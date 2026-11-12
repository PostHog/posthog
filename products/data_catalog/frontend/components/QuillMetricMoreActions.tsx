import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { MetricSceneAction } from '../metricSceneActions'

export function QuillMetricMoreActions({ actions }: { actions: MetricSceneAction[] }): JSX.Element {
    const nonDestructive = actions.filter((action) => !action.destructive)
    const destructive = actions.filter((action) => action.destructive)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label="More actions"
                        tooltip="More actions"
                        data-attr="data-catalog-metric-more-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {nonDestructive.map((action) => (
                    <DropdownMenuItem
                        key={action.key}
                        onClick={action.onClick}
                        disabledReason={action.disabledReason}
                        data-attr={`data-catalog-metric-action-${action.key}`}
                    >
                        {action.icon}
                        {action.label}
                    </DropdownMenuItem>
                ))}
                {destructive.length > 0 && <DropdownMenuSeparator />}
                {destructive.map((action) => (
                    <DropdownMenuItem
                        key={action.key}
                        variant="destructive"
                        onClick={action.onClick}
                        disabledReason={action.disabledReason}
                        data-attr={`data-catalog-metric-action-${action.key}`}
                    >
                        {action.icon}
                        {action.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
