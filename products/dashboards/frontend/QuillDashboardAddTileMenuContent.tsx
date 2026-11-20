import { Badge, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel } from '@posthog/quill'

import {
    ADD_TILE_MENU_DATA_ATTRS,
    DashboardAddTileOption,
    groupDashboardAddTileOptions,
} from './dashboardAddTileOptions'

interface QuillDashboardAddTileMenuContentProps {
    options: DashboardAddTileOption[]
    align: 'start' | 'center' | 'end'
    onBeforeSelect?: () => void
}

export function QuillDashboardAddTileMenuContent({
    options,
    align,
    onBeforeSelect,
}: QuillDashboardAddTileMenuContentProps): JSX.Element {
    return (
        <DropdownMenuContent align={align} className="min-w-40">
            {groupDashboardAddTileOptions(options).map(({ section, title, options: sectionOptions }) => (
                <DropdownMenuGroup key={section}>
                    <DropdownMenuLabel>{title}</DropdownMenuLabel>
                    {sectionOptions.map((option) => (
                        <DropdownMenuItem
                            key={option.key}
                            onClick={() => {
                                onBeforeSelect?.()
                                option.onClick()
                            }}
                            data-attr={ADD_TILE_MENU_DATA_ATTRS[option.key]}
                        >
                            {option.label}
                            {option.tag && (
                                <Badge variant="success" className="ml-auto">
                                    {option.tag.toUpperCase()}
                                </Badge>
                            )}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            ))}
        </DropdownMenuContent>
    )
}
