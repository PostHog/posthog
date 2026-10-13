import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { validateMetricName } from './common'
import type { DataCatalogTab } from './dataCatalogSceneLogic'

const SKILL_DISMISS_GROUP = 'data-catalog-skill'
const VIEW_DISMISS_GROUP = 'data-catalog-view'
const METRIC_DISMISS_GROUP = 'data-catalog-metric'

const SETTING_UP_DATA_CATALOG_SKILL = 'setting-up-data-catalog'

// All static strings below are our own build-time constants, which is what makes them safe to attach
// as trusted `instructions` items. The skill body and tool schemas are not embedded: product skills
// are installed in the agent's sandbox, and the exec MCP tool already exposes the data-catalog
// commands, so naming them is enough to skip discovery.
const SKILL_CONTEXT_ITEMS: AttachedContextItem[] = [
    {
        type: 'instructions',
        hidden: true,
        dismissGroup: SKILL_DISMISS_GROUP,
        value:
            `The user has the PostHog data catalog open. Load the ${SETTING_UP_DATA_CATALOG_SKILL} skill before your ` +
            'first tool call. Act through the data-catalog MCP tools (the exec `data-catalog-*` commands plus ' +
            'metric-list and metric-describe: discover metrics with metric-list and inspect one with ' +
            'metric-describe). Do not search for tools; use the exec `info <tool>` command when you need a full ' +
            'input schema.',
    },
    {
        type: 'skill',
        key: SETTING_UP_DATA_CATALOG_SKILL,
        label: 'Setting up data catalog skill',
        dismissGroup: SKILL_DISMISS_GROUP,
    },
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
        'The Open data catalog metric draft text item is the state of the markdown definition editor, and the latest one wins over anything earlier in the conversation. ' +
        'While editing is true its markdown is unsaved text that wins over the persisted definition when reading. ' +
        'While editing is false the editor is closed, any earlier draft was abandoned, and the persisted definition is current. ' +
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

    // Always attached, including when the editor is closed, so a closed or reverted editor
    // supersedes the draft the agent read earlier. A text item is the only shape the send-path
    // dedupe never prunes, so every send carries the current state rather than the last new value.
    contextItems.push({
        type: 'text',
        hidden: true,
        dismissGroup: METRIC_DISMISS_GROUP,
        value: `Open data catalog metric draft: ${JSON.stringify(
            draftMarkdown === null
                ? { name, editing: false }
                : { name, editing: true, kind: 'MarkdownDefinition', markdown: draftMarkdown }
        )}`,
    })

    return contextItems
}
