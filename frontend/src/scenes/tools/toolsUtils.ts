import { ANALYTICS_FILE_SYSTEM_TYPES, isFromPostHogItem } from 'scenes/analytics/analyticsUtils'
import { libraryRowOpensProduct, productObjectType } from 'scenes/library/libraryUtils'
import { urls } from 'scenes/urls'

import { getDefaultTreePersons } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsMetadata, getTreeItemsProducts } from '~/products'
import { FileSystemImport, ProductItemCategory } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

export interface ToolGroup {
    category: string
    tools: FileSystemImport[]
}

// Workspaces for building queries come first, apart from the product pages.
const PINNED_TOOL_ICONS = ['sql_editor']
export const PINNED_TOOLS_CATEGORY = 'Workspace'

/** The static pages the Products list can show. The current nav links Persons, Cohorts and Activity outside its product list. */
export function getToolSourceItems(): FileSystemImport[] {
    return [
        ...getTreeItemsProducts(),
        ...getTreeItemsMetadata(),
        ...getDefaultTreePersons(),
        {
            path: 'Activity',
            category: ProductItemCategory.ANALYTICS,
            iconType: 'activity',
            href: urls.activity(ActivityTab.ExploreEvents),
            sceneKey: 'Activity',
        },
    ]
}

export function toolLabel(tool: FileSystemImport): string {
    return tool.displayLabel || tool.path
}

export function toolCategory(tool: FileSystemImport): string {
    return PINNED_TOOL_ICONS.includes(tool.iconType ?? '') ? PINNED_TOOLS_CATEGORY : tool.category || 'Other'
}

export function toolMatchesSearch(tool: FileSystemImport, search: string): boolean {
    const query = search.trim().toLowerCase()
    return !query || `${toolLabel(tool)} ${toolCategory(tool)}`.toLowerCase().includes(query)
}

/** Whether a page gets its own row in the Products list. Library rows and the Views pane open the other pages. */
export function isToolItem(item: FileSystemImport): boolean {
    // The ready-made analytics products open from the Analytics pane, so they are not tools as well.
    return (
        !!item.href &&
        !isFromPostHogItem(item) &&
        !libraryRowOpensProduct(item) &&
        !ANALYTICS_FILE_SYSTEM_TYPES.has(productObjectType(item))
    )
}

export function groupTools(tools: FileSystemImport[], search: string): ToolGroup[] {
    const groups = new Map<string, FileSystemImport[]>()
    for (const tool of tools) {
        if (toolMatchesSearch(tool, search)) {
            const category = toolCategory(tool)
            groups.set(category, [...(groups.get(category) ?? []), tool])
        }
    }
    return [...groups.entries()]
        .map(([category, groupTools]) => ({ category, tools: groupTools }))
        .sort(
            (first, second) =>
                Number(second.category === PINNED_TOOLS_CATEGORY) - Number(first.category === PINNED_TOOLS_CATEGORY) ||
                first.category.localeCompare(second.category)
        )
}
