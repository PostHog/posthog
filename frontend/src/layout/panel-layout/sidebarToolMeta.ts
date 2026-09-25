import { sceneConfigurations } from 'scenes/scenes'

import { FileSystemImport } from '~/queries/schema/schema-general'

const descriptions: Record<string, string> = {
    Home: 'Pick up where you left off with the insights, dashboards, and activity that matter to your project.',
    Activity:
        'Explore the events people send to your project. Inspect their properties to understand exactly what happened.',
    'SQL editor':
        'Ask questions that need more than a chart builder. Query your events and warehouse tables together, then turn the results into a table or visualization.',
    'Product analytics':
        'Find out how people discover, use, and return to your product. Explore trends, conversion funnels, retention, and the paths people take.',
    Dashboards:
        'Bring related insights together in one place. Follow your key metrics over time and share the same view of progress with your team.',
    'Session replay':
        'Watch how people actually experience your product. Follow their clicks and navigation to understand the behavior behind a metric or bug report.',
    'Feature flags':
        'Choose who sees a feature without another deployment. Roll changes out gradually, target a specific group, or turn a feature off when something goes wrong.',
    Experiments:
        'Compare product changes with a controlled test. Measure their effect on the metrics you care about before deciding what to ship.',
    'Web analytics':
        'Understand who visits your website, where they come from, and which pages lead to conversions. Start with traffic, then explore what drives it.',
    'Error tracking':
        'Turn exceptions into issues you can investigate. See who was affected and connect errors with the context you need to find the cause.',
    Surveys:
        'Ask people about their experience while it is still fresh. Collect feedback in your product and use it to explain what your analytics cannot.',
    Heatmaps:
        'See where people click and how far they scroll. Spot overlooked calls to action and places where a page loses attention.',
    Notebooks:
        'Keep an investigation together with notes, insights, and recordings. Give your team the evidence and context behind your conclusions.',
    'LLM analytics':
        'Follow your AI application from prompts to responses. Inspect traces, latency, token usage, and cost to understand quality and performance.',
    Persons:
        'Explore the people behind your events, including their properties and activity. Connect an individual experience with the patterns in your analytics.',
    Cohorts:
        'Group people by what they do and who they are. Reuse those audiences in analysis, feature targeting, and experiments.',
    'SQL variables':
        'Define reusable values for SQL queries so you can change a shared parameter without editing every query.',
    'Core events':
        'Choose the events that signal meaningful use of your product. Give your team a shared starting point for understanding customer activity.',
    'Revenue definitions':
        'Tell PostHog which events represent revenue and where to find their amounts and currencies. Use consistent revenue measures across your analyses.',
    'Property groups':
        'Organize related properties into reusable groups. Make a large tracking schema easier to navigate and understand.',
    'Event definitions':
        'Explore the events captured in your project and document what they mean. Help your team choose the right events for an analysis.',
    'Property definitions':
        'Explore the properties attached to your events and people. Document their meaning so everyone interprets the same data consistently.',
    'Managed viewsets':
        'Set up collections of warehouse views built for a particular kind of analysis. Reuse prepared data models instead of starting each query from scratch.',
    'Event ingestion warnings':
        'Find problems encountered while processing your events. Inspect the warnings to identify tracking issues and improve the data you analyze.',
    Annotations:
        'Add context to changes in your metrics. Mark releases, campaigns, and other milestones so your team can connect a chart with what happened.',
    Sources:
        'Bring data from your other tools into PostHog. Combine it with product events to answer questions that span your business.',
    Destinations:
        'Send events from PostHog to the tools that need them. Connect product activity with the rest of your workflows.',
    Transformations:
        'Reshape incoming events before they reach your analyses. Keep event names and properties consistent across your tracking.',
    Models: 'Turn SQL queries into reusable views and materialized views. Build on shared data models instead of repeating the same preparation in every analysis.',
}

/**
 * Tree items whose product has no page on posthog.com/docs yet, so they show no docs link.
 * Every other sidebar tool must have one — `sidebarToolMeta.test.ts` fails when a new tool has neither.
 */
export const SIDEBAR_TOOLS_WITHOUT_DOCS = new Set<string>([
    'AI gateway',
    'Apps',
    'Broadcasts',
    'Business knowledge',
    'Engineering analytics',
    'Identity matching',
    'Links',
    'Live Debugger',
    'Product tours',
    'Pulse',
    'User research',
    'Visual review',
    'Wizard',
])

export interface SidebarToolMeta {
    description?: string
    docsHref?: string
}

/** Shared descriptions for app tooltips and sidebar settings, with docs from the scene config. */
export function sidebarToolMeta(product: FileSystemImport): SidebarToolMeta {
    // Most tree items name their scene explicitly; the rest are generated with a single-scene list.
    const sceneKey = product.sceneKey ?? (product.sceneKeys?.length === 1 ? product.sceneKeys[0] : undefined)
    const sceneConfig = sceneKey ? sceneConfigurations[sceneKey] : undefined
    const isGroup =
        product.iconType === 'group' || product.iconType?.startsWith('group_') || product.type?.startsWith('group_')
    return {
        // Group paths come from configurable group type names, which can match a built-in app name.
        description: isGroup
            ? 'Explore the organizations, accounts, or other groups behind your events. Understand usage at the group level.'
            : (descriptions[product.path] ?? sceneConfig?.description),
        docsHref: sceneConfig?.docsHref,
    }
}
