import { Breadcrumb } from '~/types'
import { Scene } from '~/scenes/sceneTypes'
import { urls } from '~/scenes/urls'
import { productUrls } from '~/products'
import { DataManagementTab } from '~/scenes/data-management/DataManagementScene'

export interface BreadcrumbPath {
    key: string | Scene
    name: string
    path?: string
    tab?: string
}

/**
 * Generates breadcrumbs from a hierarchical path structure
 * This utility helps maintain consistent breadcrumb generation from manifest hierarchies
 */
export function generateBreadcrumbs(paths: BreadcrumbPath[]): Breadcrumb[] {
    return paths.map(({ key, name, path, tab }) => ({
        key: tab ? [key, tab] : key,
        name,
        ...(path ? { path } : {}),
    }))
}

/**
 * Common breadcrumb patterns for different areas of the app
 */
export const breadcrumbPatterns = {
    dataManagement: {
        actions: (actionName?: string, isEdit?: boolean): Breadcrumb[] =>
            generateBreadcrumbs([
                {
                    key: Scene.DataManagement,
                    name: 'Data management',
                    path: urls.eventDefinitions(),
                },
                {
                    key: DataManagementTab.Actions,
                    name: 'Actions',
                    path: productUrls.actions(),
                },
                {
                    key: Scene.Action,
                    name: actionName || (isEdit ? 'Edit action' : 'New action'),
                    tab: isEdit ? 'edit' : 'new',
                },
            ]),
    },
}

/**
 * Auto-generates breadcrumbs from a manifest hierarchy path
 * Example: ['DataManagement', 'Actions'] -> Data management > Actions
 */
export function generateBreadcrumbsFromHierarchy(
    hierarchyPath: string[],
    currentItemName?: string,
    currentItemKey?: string | Scene
): Breadcrumb[] {
    const breadcrumbs: Breadcrumb[] = []

    // Map hierarchy paths to their configurations
    const hierarchyMap: Record<string, { name: string; url?: string; key?: string | Scene }> = {
        DataManagement: {
            name: 'Data management',
            url: urls.eventDefinitions(),
            key: Scene.DataManagement,
        },
        Actions: {
            name: 'Actions',
            url: productUrls.actions(),
            key: DataManagementTab.Actions,
        },
        // Add more hierarchy mappings as needed
    }

    // Generate breadcrumbs for the hierarchy path
    hierarchyPath.forEach((pathSegment) => {
        const config = hierarchyMap[pathSegment]
        if (config) {
            breadcrumbs.push({
                key: config.key || pathSegment,
                name: config.name,
                ...(config.url ? { path: config.url } : {}),
            })
        }
    })

    // Add the current item as the final breadcrumb
    if (currentItemName) {
        breadcrumbs.push({
            key: currentItemKey || 'current',
            name: currentItemName,
        })
    }

    return breadcrumbs
}
