import { VIEW_FILE_SYSTEM_TYPES, libraryRowOpensProduct, productObjectType } from 'scenes/library/libraryUtils'
import { urls } from 'scenes/urls'
import { VIEW_TYPES, ViewTypeInfo } from 'scenes/views/viewsUtils'

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
    return !!item.href && !libraryRowOpensProduct(item) && !VIEW_FILE_SYSTEM_TYPES.has(productObjectType(item))
}

// A shorter search, like "da", matches too many words to mean a view type.
const VIEW_TYPE_SEARCH_MIN_LENGTH = 3

/** The view types a Products search looks for. Those types live in the Views pane, so the pane points there. */
export function viewTypesForProductSearch(search: string): ViewTypeInfo[] {
    const query = search.trim().toLowerCase()
    if (query.length < VIEW_TYPE_SEARCH_MIN_LENGTH) {
        return []
    }
    return VIEW_TYPES.filter(
        (info) =>
            VIEW_FILE_SYSTEM_TYPES.has(info.type) &&
            (info.pluralLabel.toLowerCase().includes(query) || query.includes(info.label.toLowerCase()))
    )
}

let productLabelsByLibraryType: Map<string, string[]> | null = null

/** The names of the products a Library type row opens, so a search for "Product analytics" finds Insights. */
export function libraryRowProductLabels(type: string): string[] {
    if (!productLabelsByLibraryType) {
        const labels = new Map<string, string[]>()
        for (const item of getToolSourceItems()) {
            if (libraryRowOpensProduct(item)) {
                const itemType = productObjectType(item)
                labels.set(itemType, [...(labels.get(itemType) ?? []), toolLabel(item)])
            }
        }
        productLabelsByLibraryType = labels
    }
    return productLabelsByLibraryType.get(type) ?? []
}

export function toolHrefForPath(
    path: string,
    tools: Pick<FileSystemImport, 'href'>[] = getToolSourceItems().filter(isToolItem)
): string | null {
    let match: { href: string; toolPath: string } | null = null
    for (const { href } of tools) {
        const toolPath = href?.split(/[?#]/)[0]
        if (
            href &&
            toolPath &&
            (path === toolPath || path.startsWith(`${toolPath}/`)) &&
            (!match || toolPath.length > match.toolPath.length)
        ) {
            match = { href, toolPath }
        }
    }
    return match?.href ?? null
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
