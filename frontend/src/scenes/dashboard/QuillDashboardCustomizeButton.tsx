import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGridMasonry } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { dashboardLogic } from './dashboardLogic'

export function QuillDashboardCustomizeButton(): JSX.Element {
    const { setDashboardEditing } = useActions(dashboardLogic)
    const { currentLayoutSize } = useValues(dashboardLogic)
    const layoutAvailable = currentLayoutSize !== 'xs'

    if (!layoutAvailable) {
        return (
            <Popover>
                <PopoverTrigger
                    render={<Button variant="outline" data-attr="dashboard-edit-layout-customize-dropdown" />}
                >
                    <IconGridMasonry />
                    Customize
                </PopoverTrigger>
                <PopoverContent align="end" className="w-auto p-0">
                    <DashboardCustomizeMenu />
                </PopoverContent>
            </Popover>
        )
    }

    return (
        <ButtonGroup>
            <Shortcut
                name="EnterEditMode"
                scope={Scene.Dashboard}
                keybind={[keyBinds.edit]}
                intent="Enter edit mode"
                interaction="click"
            >
                <Button
                    variant="outline"
                    data-attr="dashboard-edit-mode-button"
                    onClick={() =>
                        setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.SceneCommonButtons)
                    }
                    tooltip="Customize dashboard"
                >
                    <IconGridMasonry />
                    Customize
                </Button>
            </Shortcut>
            <Popover>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <PopoverTrigger
                                render={
                                    <Button
                                        variant="outline"
                                        size="icon"
                                        aria-label="Customize options"
                                        data-attr="dashboard-edit-layout-customize-dropdown"
                                    />
                                }
                            />
                        }
                    >
                        <IconChevronDown />
                    </TooltipTrigger>
                    <TooltipContent>Customize options</TooltipContent>
                </Tooltip>
                <PopoverContent align="end" className="w-auto p-0">
                    <DashboardCustomizeMenu />
                </PopoverContent>
            </Popover>
        </ButtonGroup>
    )
}
