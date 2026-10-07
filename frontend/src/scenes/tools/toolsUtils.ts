import { TOOL_FILE_SYSTEM_TYPES } from 'scenes/library/libraryUtils'

import { fileSystemTypes, getTreeItemsMetadata, getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'

export interface ToolGroup {
    category: string
    tools: FileSystemImport[]
}

// Workspaces for building queries come first, apart from the product pages.
const PINNED_TOOL_ICONS = ['sql_editor']
export const PINNED_TOOLS_CATEGORY = 'Workspace'

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

// Saved object types live in Library, except the ones that are working pages.
export function isToolItem(item: FileSystemImport): boolean {
    const type = item.type?.split('/')[0] || item.iconType || ''
    return !!item.href && !(type in fileSystemTypes && !TOOL_FILE_SYSTEM_TYPES.has(type))
}

export function toolHrefForPath(
    path: string,
    tools: Pick<FileSystemImport, 'href'>[] = [...getTreeItemsProducts(), ...getTreeItemsMetadata()].filter(isToolItem)
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
