import { routes, sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { ASSISTANT_NAVIGATE_URLS, AssistantNavigateUrl } from '~/queries/schema/schema-assistant-messages'

import { TOOL_DEFINITIONS } from '../max-constants'

/**
 * Build available pages context with descriptions for the navigate tool
 */
export function buildSceneDescriptionsContext(): string {
    const pageEntries: string[] = []
    for (const urlKey of Object.keys(urls)) {
        if (!ASSISTANT_NAVIGATE_URLS.has(urlKey as AssistantNavigateUrl)) {
            continue
        }
        let baseUrl: string
        try {
            // Call the URL function with nothing to get the base URL route
            // @ts-expect-error - we can ignore the error about expecting more than 0 args
            baseUrl = urls[urlKey as keyof typeof urls]()
        } catch {
            // Skip URLs that require parameters or fail to resolve
            continue
        }
        // Look up the Scene enum from the routes mapping
        const routeInfo = routes[baseUrl]
        if (!routeInfo) {
            continue
        }
        const [sceneKey] = routeInfo
        const sceneConfig = sceneConfigurations[sceneKey]
        // Find tools available on this scene
        const availableTools = Object.entries(TOOL_DEFINITIONS)
            .filter(([_, toolDef]) => toolDef.product === sceneKey)
            .map(([_, toolDef]) => toolDef.name)
        if (!sceneConfig.description && !availableTools.length) {
            continue // No extra details, and the key itself is already included in the navigate tool's definition
        }
        let entry = `- **${urlKey}**`
        if (sceneConfig.description) {
            entry += `: ${sceneConfig.description}`
        }
        if (availableTools.length > 0) {
            entry += ` [tools: ${availableTools.join(', ')}]`
        }
        pageEntries.push(entry)
    }

    return pageEntries.join('\n')
}
