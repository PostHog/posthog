import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { validateMetricName } from './common'
import type { DataCatalogTab } from './dataCatalogSceneLogic'
import { DATA_CATALOG_MCP_TOOLS, SETTING_UP_DATA_CATALOG_SKILL } from './generated/agentContext'

const SKILL_DISMISS_GROUP = 'data-catalog-skill'
const VIEW_DISMISS_GROUP = 'data-catalog-view'
const METRIC_DISMISS_GROUP = 'data-catalog-metric'

const SKILL_CONTEXT_ITEMS: AttachedContextItem[] = [
    {
        type: 'instructions',
        hidden: true,
        dismissGroup: SKILL_DISMISS_GROUP,
        value:
            'The full setting-up-data-catalog skill and complete data-catalog MCP tool catalog are included in this context. ' +
            'Call the listed tools directly, and use the exec `info <tool>` command only when you need a full input schema. ' +
            'Discover metrics with metric-list and inspect one with metric-describe.',
    },
    {
        type: 'instructions',
        hidden: true,
        dismissGroup: SKILL_DISMISS_GROUP,
        value: `Skill ${SETTING_UP_DATA_CATALOG_SKILL.name} (embedded): ${SETTING_UP_DATA_CATALOG_SKILL.content}`,
    },
    {
        type: 'skill',
        key: SETTING_UP_DATA_CATALOG_SKILL.name,
        label: 'Setting up data catalog skill',
        dismissGroup: SKILL_DISMISS_GROUP,
    },
    ...DATA_CATALOG_MCP_TOOLS.map((tool) => ({
        type: 'instructions' as const,
        hidden: true,
        dismissGroup: SKILL_DISMISS_GROUP,
        value: `MCP tool ${tool.name}: ${tool.description}`,
    })),
]

const CATALOG_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: VIEW_DISMISS_GROUP,
    value:
        'The user has the data catalog open. The Open data catalog tab text item names the current tab, and the latest item wins. ' +
        'Completed data-catalog tool calls are reflected live on the open page, so make the change rather than narrate it. ' +
        'Promotion tools still require the user to type their confirmation.',
}

const METRIC_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: METRIC_DISMISS_GROUP,
    value:
        'The data_catalog_metric item is the open metric and the Open data catalog metric text item names it. ' +
        'The data_catalog_metric_draft item, when present, is the unsaved markdown definition being edited and wins over the persisted definition when reading. ' +
        'Updating, approving, or refreshing this metric refreshes the page. Renaming it moves the page to the new name and keeps any open edit.',
}

export const DATA_CATALOG_AGENT_HEADLINES = ['How can I help with this data catalog?', 'What would you like to update?']

export const DATA_CATALOG_METRIC_AGENT_HEADLINES = [
    'How can I help with this metric?',
    'What would you like to change?',
]

export function buildDataCatalogAgentContext(activeTab: DataCatalogTab): AttachedContextItem[] {
    return [
        ...SKILL_CONTEXT_ITEMS,
        CATALOG_CONTEXT_ITEM,
        {
            type: 'text',
            hidden: true,
            value: `Open data catalog tab: ${activeTab}`,
            dismissGroup: VIEW_DISMISS_GROUP,
        },
    ]
}

export function buildDataCatalogMetricAgentContext(name: string, draftMarkdown: string | null): AttachedContextItem[] {
    if (validateMetricName(name)) {
        return SKILL_CONTEXT_ITEMS
    }

    const contextItems: AttachedContextItem[] = [
        ...SKILL_CONTEXT_ITEMS,
        METRIC_CONTEXT_ITEM,
        {
            type: 'data_catalog_metric',
            key: name,
            label: name,
            dismissGroup: METRIC_DISMISS_GROUP,
        },
        {
            type: 'text',
            hidden: true,
            value: `Open data catalog metric: ${name}`,
            dismissGroup: METRIC_DISMISS_GROUP,
        },
    ]

    if (draftMarkdown !== null) {
        contextItems.push({
            type: 'data_catalog_metric_draft',
            hidden: true,
            dismissGroup: METRIC_DISMISS_GROUP,
            value: JSON.stringify({ name, kind: 'MarkdownDefinition', markdown: draftMarkdown }),
        })
    }

    return contextItems
}
