import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconChevronRight, IconSparkles } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { runBlankDashboardFlow } from 'scenes/dashboard/dashboards/templates/dashboardTemplateCreationFlows'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemIconType } from '~/queries/schema/schema-general'

// Products shown first, in this exact order. Anything not listed follows alphabetically.
const PRIORITY_ORDER = ['Insight', 'Dashboard', 'Notebook', 'Experiment', 'Feature flag']

// Products hidden from the Create menu.
const HIDDEN = new Set(['Action', 'Cohort', 'Data', 'Early access feature', 'Link', 'Product tour'])

// Icon overrides for group (submenu) triggers, keyed by the stable item key.
const GROUP_ICONS: Record<string, FileSystemIconType> = {
    Insight: 'product_analytics',
}

// Stable key for an item, independent of the "New ..." display name the tree assigns.
function keyOf(item: TreeDataItem): string {
    return item.record?.path ?? item.name ?? item.id
}

// Clean, sentence-cased label derived from the path (e.g. "Insight/Funnel" -> "Funnel"),
// avoiding the "New ..." prefix the project tree adds for create links.
function labelFor(item: TreeDataItem): string {
    const last = splitPath(keyOf(item)).pop()
    return unescapePath(last ?? keyOf(item))
}

function rankOf(item: TreeDataItem): number {
    const index = PRIORITY_ORDER.indexOf(keyOf(item))
    return index === -1 ? PRIORITY_ORDER.length : index
}

function sortByPriority(a: TreeDataItem, b: TreeDataItem): number {
    const rankDiff = rankOf(a) - rankOf(b)
    return rankDiff !== 0 ? rankDiff : labelFor(a).localeCompare(labelFor(b), undefined, { sensitivity: 'accent' })
}

function captureItemClicked(item: string): void {
    posthog.capture('nav create menu item clicked', { item })
}

function pushHref(item: TreeDataItem): void {
    if (item.record?.href) {
        router.actions.push(
            typeof item.record.href === 'function' ? item.record.href(item.record.ref) : item.record.href
        )
    }
}

export function CreateMenu(): JSX.Element {
    const { treeItemsNew } = useValues(projectTreeDataLogic)
    const { isLoading } = useValues(newDashboardLogic)
    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { addDashboard, setIsLoading } = useActions(newDashboardLogic)

    const items = treeItemsNew.filter((item) => !HIDDEN.has(keyOf(item))).sort(sortByPriority)

    return (
        <DropdownMenuGroup>
            <DropdownMenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    captureItemClicked('Create with AI')
                    openSidePanelMax()
                }}
                data-attr="create-menu-with-ai-button"
            >
                <ButtonPrimitive menuItem>
                    <IconSparkles className="text-accent" />
                    Create with AI
                </ButtonPrimitive>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {items.map((item): JSX.Element => {
                if (keyOf(item) === 'Dashboard') {
                    return (
                        <DropdownMenuSub key={item.id}>
                            <DropdownMenuSubTrigger asChild>
                                <ButtonPrimitive menuItem data-attr={`create-menu-sub-menu-${keyOf(item)}-button`}>
                                    {item.icon}
                                    {labelFor(item)}
                                    <IconChevronRight className="ml-auto size-3" />
                                </ButtonPrimitive>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuGroup>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            captureItemClicked('Dashboard (blank)')
                                            runBlankDashboardFlow({ isLoading, setIsLoading, addDashboard })
                                        }}
                                        data-attr="create-menu-dashboard-blank"
                                    >
                                        <ButtonPrimitive menuItem>Start from scratch</ButtonPrimitive>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        asChild
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            captureItemClicked('Dashboard (templates)')
                                            pushHref(item)
                                        }}
                                        data-attr="create-menu-dashboard-templates"
                                    >
                                        <ButtonPrimitive menuItem>View templates</ButtonPrimitive>
                                    </DropdownMenuItem>
                                </DropdownMenuGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )
                }
                if (item.children) {
                    const groupIcon = GROUP_ICONS[keyOf(item)]
                    return (
                        <DropdownMenuSub key={item.id}>
                            <DropdownMenuSubTrigger asChild>
                                <ButtonPrimitive menuItem data-attr={`create-menu-sub-menu-${keyOf(item)}-button`}>
                                    {groupIcon ? iconForType(groupIcon) : item.icon}
                                    {labelFor(item)}
                                    <IconChevronRight className="ml-auto size-3" />
                                </ButtonPrimitive>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuGroup>
                                    {item.children.map((child) => (
                                        <DropdownMenuItem
                                            key={child.id}
                                            asChild
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                captureItemClicked(keyOf(child))
                                                pushHref(child)
                                            }}
                                            data-attr={`create-menu-sub-menu-${keyOf(child)}-button`}
                                        >
                                            <ButtonPrimitive menuItem>
                                                {child.icon}
                                                {labelFor(child)}
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )
                }
                return (
                    <DropdownMenuItem
                        key={item.id}
                        asChild
                        onClick={(e) => {
                            e.stopPropagation()
                            captureItemClicked(keyOf(item))
                            pushHref(item)
                        }}
                    >
                        <ButtonPrimitive menuItem data-attr={`create-menu-new-${keyOf(item)}-button`}>
                            {item.icon}
                            {labelFor(item)}
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )
            })}
        </DropdownMenuGroup>
    )
}
