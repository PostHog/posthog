import { HOMEPAGE_SUGGESTION_TOPICS, SuggestionTopic, TopicSuggestion } from 'scenes/max/suggestionTopics'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { Conversation } from '~/types'

import type { HomepageGridItem } from './aiFirstHomepageLogic'

// Matches the 4 suggestions every topic panel shows, so toggling a topic badge
// swaps 4 identical card units for 4 others and the layout never shifts.
export const SUGGESTIONS_LIMIT = 4
const RECENT_PROMPTS_LIMIT = 2

interface RecentPromptTemplate {
    title: string
    prompt: (name: string) => string
}

// Prompt templates keyed by file-system entry type. Entry types can carry a subtype
// suffix (e.g. `insight/trends`), so lookups match on the segment before `/`.
// Types without a template produce no prompt: a generic question about an arbitrary
// entity reads as filler, not as a suggestion grounded in the user's activity.
// `title` is the card headline; the entity name goes in the caption, and `prompt`
// grounds the full question with the name for the agent. Each type carries several
// templates, mixing analysis with a next step in another product; one is picked per
// entity by a stable hash so the suggestion varies across entities without flickering
// across renders.
const RECENT_PROMPT_TEMPLATES: Record<string, RecentPromptTemplate[]> = {
    dashboard: [
        { title: 'What changed this week?', prompt: (name) => `What changed in "${name}" this week?` },
        {
            title: 'Find anomalies',
            prompt: (name) => `Are there anomalies in the metrics on the "${name}" dashboard?`,
        },
    ],
    insight: [
        { title: 'Explain what this shows', prompt: (name) => `Explain what "${name}" shows` },
        { title: 'Explain recent changes', prompt: (name) => `Why did "${name}" change recently?` },
        {
            title: 'Watch the users behind it',
            prompt: (name) => `Find session recordings of the users behind "${name}"`,
        },
    ],
    experiment: [
        { title: 'How is this experiment doing?', prompt: (name) => `How is the "${name}" experiment doing?` },
        {
            title: 'Should I ship it?',
            prompt: (name) => `Has the "${name}" experiment reached significance? Should I ship it?`,
        },
    ],
    feature_flag: [
        {
            title: 'Analyze the impact of this flag',
            prompt: (name) => `Analyze how the "${name}" feature flag affects user behavior and key metrics`,
        },
        {
            title: 'Turn this flag into an experiment',
            prompt: (name) => `Create an experiment to measure the impact of the "${name}" feature flag`,
        },
        {
            title: 'Check if this flag can be removed',
            prompt: (name) => `Is the "${name}" flag fully rolled out? Check if it is safe to remove from my code`,
        },
    ],
    survey: [
        { title: 'Summarize the responses', prompt: (name) => `Summarize the responses to "${name}"` },
        {
            title: 'Find themes in the responses',
            prompt: (name) => `What are the main themes in the responses to "${name}"?`,
        },
    ],
}

// Stable per-entity template pick: varied across entities, constant across renders.
function pickTemplate(templates: RecentPromptTemplate[], entityId: string): RecentPromptTemplate {
    let hash = 0
    for (let i = 0; i < entityId.length; i++) {
        hash = (hash * 31 + entityId.charCodeAt(i)) >>> 0
    }
    return templates[hash % templates.length]
}

function entryName(entry: FileSystemEntry): string | null {
    const name = splitPath(entry.path).pop()
    return name ? unescapePath(name) : null
}

// A topic without a product icon (e.g. Learn) sets a placeholder iconType plus an explicit
// icon element; prefer the element so the card doesn't render the dashed placeholder circle.
function suggestionVisual(
    topic: SuggestionTopic,
    suggestion: TopicSuggestion
): Pick<HomepageGridItem, 'icon' | 'itemType'> {
    if (!suggestion.iconType && topic.icon) {
        return { icon: topic.icon, itemType: null }
    }
    return { itemType: suggestion.iconType ?? topic.iconType }
}

/**
 * Composes the homepage "Suggestions" column: continue the last conversation, then prompts
 * inferred from recently visited items, then static topic prompts as fill. The static
 * fill guarantees the column is never empty once its sources have loaded.
 */
export function buildSuggestionItems(
    lastConversation: Conversation | null,
    recentItems: FileSystemEntry[]
): HomepageGridItem[] {
    const items: HomepageGridItem[] = []

    if (lastConversation?.title) {
        items.push({
            id: `suggestion-continue-${lastConversation.id}`,
            label: 'Continue your last conversation',
            description: lastConversation.title,
            kind: 'suggestion',
            source: 'continue',
            conversationId: lastConversation.id,
        })
    }

    // One prompt per entity type, so two recently viewed dashboards don't produce two
    // near-identical questions.
    const usedTypePrefixes = new Set<string>()
    for (const entry of recentItems) {
        if (usedTypePrefixes.size >= RECENT_PROMPTS_LIMIT) {
            break
        }
        const typePrefix = (entry.type ?? '').split('/')[0]
        const templates = RECENT_PROMPT_TEMPLATES[typePrefix]
        const name = entryName(entry)
        if (!templates || !name || usedTypePrefixes.has(typePrefix)) {
            continue
        }
        usedTypePrefixes.add(typePrefix)
        const template = pickTemplate(templates, entry.id)
        items.push({
            id: `suggestion-recent-${entry.id}`,
            label: template.title,
            description: name,
            kind: 'suggestion',
            source: 'recent',
            prompt: template.prompt(name),
            itemType: entry.type ?? null,
        })
    }

    // Fill with static prompts, round-robin across topics so the fill covers different
    // products instead of exhausting one topic's list first. Fill-in suggestions
    // (`requiresUserInput`) are prefixes waiting for user text, so submitting one directly
    // would send an incomplete prompt: skip them.
    const maxDepth = Math.max(...HOMEPAGE_SUGGESTION_TOPICS.map((topic) => topic.suggestions.length))
    for (let depth = 0; depth < maxDepth && items.length < SUGGESTIONS_LIMIT; depth++) {
        for (const topic of HOMEPAGE_SUGGESTION_TOPICS) {
            if (items.length >= SUGGESTIONS_LIMIT) {
                break
            }
            const suggestion = topic.suggestions[depth]
            if (!suggestion || suggestion.requiresUserInput || suggestion.hint) {
                continue
            }
            items.push({
                id: `suggestion-static-${topic.key}-${depth}`,
                // Docs-style suggestions carry only `content`, so fall back to it as the headline
                label: suggestion.title ?? suggestion.content,
                description: suggestion.description,
                kind: 'suggestion',
                source: 'static',
                prompt: suggestion.content,
                ...suggestionVisual(topic, suggestion),
            })
        }
    }

    return items.slice(0, SUGGESTIONS_LIMIT)
}

/**
 * Maps a topic's suggestions to grid items, so the badge-filtered view renders through
 * the exact same list component as the default suggestions.
 */
export function topicSuggestionItems(topic: SuggestionTopic): HomepageGridItem[] {
    // Some topics carry more suggestions than the homepage shows (e.g. Learn has 5); cap at
    // the shared limit so toggling a topic badge never changes the list height.
    return topic.suggestions.slice(0, SUGGESTIONS_LIMIT).map((suggestion, index) => ({
        id: `suggestion-topic-${topic.key}-${index}`,
        label: suggestion.title ?? suggestion.content,
        description: suggestion.description,
        kind: 'suggestion',
        source: 'topic',
        prompt: suggestion.content,
        ...suggestionVisual(topic, suggestion),
        // Fill-in suggestions type a prefix and wait for the user to complete it
        fillInHint: suggestion.requiresUserInput ? (suggestion.hint ?? 'the details') : undefined,
    }))
}
