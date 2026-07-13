import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'

import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { sentimentEvaluationAvailabilityLogic } from '../sentimentEvaluationAvailabilityLogic'
import { fetchSentimentGenerationsPage, GENERATIONS_PAGE_SIZE, type SentimentGeneration } from '../sentimentQueries'
import type { MessageSentiment } from '../sentimentResults'
import { extractContentText } from '../sentimentUtils'
import type { aiObservabilitySentimentLogicType } from './aiObservabilitySentimentLogicType'

export type { SentimentGeneration } from '../sentimentQueries'

export type SentimentCategory = 'positive' | 'negative' | 'neutral'

/** @deprecated Use SentimentCategory with activeFilters set instead */
export type SentimentFilterLabel = SentimentCategory | 'both'

/** A generation paired with the index of the best matching message for display */
export interface SentimentCard {
    generation: SentimentGeneration
    /** Index into the generation's user messages array for the highest-intensity matching message */
    messageIndex: number
    sentiment: MessageSentiment
}

/** Multiple cards with the same user message text, collapsed into a single row */
export interface GroupedSentimentCard {
    /** Representative card (first/most recent occurrence) */
    card: SentimentCard
    /** Number of distinct traces with this same message */
    traceCount: number
}

export type AIObservabilitySentimentLogicProps = Record<string, never>

/** Stop auto-loading once we have at least this many visible cards */
const MIN_VISIBLE_CARDS = 50
/** Cap how many extra pages we fetch automatically to avoid runaway API calls */
const MAX_AUTO_LOAD_ROUNDS = 3
// Match backend MAX_MESSAGE_CHARS (2000) so training data captures the same text window the model classified
export const CLASSIFIER_WINDOW = 2000
/** Number of other visible cards to sample as negative (impressed) examples per engagement */
const IMPRESSION_SAMPLE_SIZE = 5

/** Parse aiInput and return the raw content text for the message at the given index, or '' on failure */
function getRawMessageText(aiInput: unknown, messageIndex: number): string {
    try {
        const parsed = typeof aiInput === 'string' ? JSON.parse(aiInput) : aiInput
        if (!Array.isArray(parsed)) {
            return ''
        }
        return extractContentText(parsed[messageIndex]?.content)
    } catch {
        return ''
    }
}

function getCardMessageText(card: SentimentCard): string {
    const text = getRawMessageText(card.generation.aiInput, card.messageIndex).trim()
    // Group by the same trailing window the classifier processes so messages
    // that differ only in a prefix (e.g. varying system prompt headers) are
    // correctly treated as duplicates.
    return text.slice(-CLASSIFIER_WINDOW)
}

function getSnippetFromCard(card: SentimentCard): string {
    return getRawMessageText(card.generation.aiInput, card.messageIndex).slice(-CLASSIFIER_WINDOW)
}

/** Fisher-Yates shuffle on a copy, return first n elements */
function sampleCards(cards: GroupedSentimentCard[], n: number): GroupedSentimentCard[] {
    if (cards.length <= n) {
        return cards
    }
    const shuffled = [...cards]
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1))
        ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
    }
    return shuffled.slice(0, n)
}

function cardKey(card: SentimentCard): string {
    return `${card.generation.uuid}:${card.messageIndex}`
}

function captureEngagementEvents(
    engagementType: 'expanded' | 'trace_clicked',
    card: SentimentCard,
    allVisibleCards: GroupedSentimentCard[],
    activeFilters: Set<SentimentCategory>,
    intensityThreshold: number
): void {
    const interactionId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    const engagedKey = cardKey(card)
    const cardPosition = allVisibleCards.findIndex((g) => cardKey(g.card) === engagedKey)
    const sentimentFilterValue = Array.from(activeFilters).sort().join(',')

    // Positive example: the card the user engaged with
    posthog.capture('llma sentiment card engaged', {
        interaction_id: interactionId,
        engagement_type: engagementType,
        generation_uuid: card.generation.uuid,
        trace_id: card.generation.traceId,
        message_index: card.messageIndex,
        message_text_snippet: getSnippetFromCard(card),
        model_prediction_label: card.sentiment.label,
        model_prediction_score: card.sentiment.score,
        ai_model: card.generation.model,
        sentiment_filter: sentimentFilterValue,
        intensity_threshold: intensityThreshold,
        card_position: cardPosition,
        visible_card_count: allVisibleCards.length,
    })

    // Negative examples: sample of other visible cards not interacted with
    const otherCards = allVisibleCards.filter((g) => cardKey(g.card) !== engagedKey)
    const sampled = sampleCards(otherCards, IMPRESSION_SAMPLE_SIZE)
    for (const { card: impressedCard } of sampled) {
        const impressedPosition = allVisibleCards.findIndex((g) => cardKey(g.card) === cardKey(impressedCard))
        posthog.capture('llma sentiment card impressed', {
            interaction_id: interactionId,
            generation_uuid: impressedCard.generation.uuid,
            trace_id: impressedCard.generation.traceId,
            message_index: impressedCard.messageIndex,
            message_text_snippet: getSnippetFromCard(impressedCard),
            model_prediction_label: impressedCard.sentiment.label,
            model_prediction_score: impressedCard.sentiment.score,
            ai_model: impressedCard.generation.model,
            card_position: impressedPosition,
            sentiment_filter: sentimentFilterValue,
            intensity_threshold: intensityThreshold,
            trigger_event: engagementType,
            trigger_generation_uuid: card.generation.uuid,
        })
    }
}

// Tracks the raw (pre-dedup) count from the last loadMoreGenerations fetch,
// so the listener can determine hasMore accurately despite deduplication.
let lastRawFetchCount = 0
let nextGenerationsOffset = 0

export const aiObservabilitySentimentLogic = kea<aiObservabilitySentimentLogicType>([
    path(['products', 'ai_observability', 'frontend', 'tabs', 'aiObservabilitySentimentLogic']),
    props({} as AIObservabilitySentimentLogicProps),
    connect(() => ({
        values: [
            aiObservabilitySharedLogic,
            ['dateFilter', 'shouldFilterTestAccounts', 'propertyFilters', 'activeTab'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            sentimentEvaluationAvailabilityLogic,
            ['hasLoadedSentimentEvaluations', 'hasSentimentEvaluations', 'sentimentEvaluationsLoading'],
        ],
    })),

    actions({
        activate: true,
        /** @deprecated Use toggleSentimentCategory instead */
        setSentimentFilter: (sentimentFilter: SentimentFilterLabel) => ({ sentimentFilter }),
        toggleSentimentCategory: (category: SentimentCategory) => ({ category }),
        setIntensityThreshold: (intensityThreshold: number) => ({ intensityThreshold }),
        toggleCardExpanded: (cardKey: string) => ({ cardKey }),
        loadMoreGenerations: true,
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        trackTraceClicked: (card: SentimentCard) => ({ card }),
    }),

    reducers({
        sentimentFilter: [
            'both' as SentimentFilterLabel,
            {
                setSentimentFilter: (_, { sentimentFilter }) => sentimentFilter,
            },
        ],
        activeFilters: [
            new Set<SentimentCategory>(['positive', 'negative']) as Set<SentimentCategory>,
            {
                toggleSentimentCategory: (state, { category }) => {
                    const next = new Set(state)
                    if (next.has(category)) {
                        // Don't allow deselecting all — keep at least one
                        if (next.size > 1) {
                            next.delete(category)
                        }
                    } else {
                        next.add(category)
                    }
                    return next
                },
            },
        ],
        intensityThreshold: [
            0.5,
            {
                setIntensityThreshold: (_, { intensityThreshold }) => intensityThreshold,
            },
        ],
        expandedCardIds: [
            new Set<string>(),
            {
                toggleCardExpanded: (state, { cardKey }) => {
                    const newSet = new Set(state)
                    if (newSet.has(cardKey)) {
                        newSet.delete(cardKey)
                    } else {
                        newSet.add(cardKey)
                    }
                    return newSet
                },
                loadGenerations: () => new Set<string>(),
            },
        ],
        hasMore: [
            true as boolean,
            {
                setHasMore: (_, { hasMore }) => hasMore,
                loadGenerations: () => true,
            },
        ],
        autoLoadRounds: [
            0 as number,
            {
                loadGenerations: () => 0,
                loadMoreGenerations: (state: number) => state + 1,
            },
        ],
        hasLoadedOnce: [
            false as boolean,
            {
                loadGenerations: () => true,
            },
        ],
        generationsError: [
            false as boolean,
            {
                loadGenerations: () => false,
                loadGenerationsFailure: () => true,
                loadGenerationsSuccess: () => false,
            },
        ],
    }),

    loaders(({ values }) => ({
        generations: [
            [] as SentimentGeneration[],
            {
                loadGenerations: async () => {
                    const page = await fetchSentimentGenerationsPage(values, 0)
                    lastRawFetchCount = page.rawCount
                    nextGenerationsOffset = page.rawCount
                    return page.generations
                },
                loadMoreGenerations: async () => {
                    const existing = values.generations
                    const page = await fetchSentimentGenerationsPage(values, nextGenerationsOffset)
                    lastRawFetchCount = page.rawCount
                    nextGenerationsOffset += page.rawCount
                    const existingGenerationIds = new Set(existing.map((g) => g.uuid))
                    const unique = page.generations.filter((g) => !existingGenerationIds.has(g.uuid))
                    return [...existing, ...unique]
                },
            },
        ],
    })),

    selectors({
        taxonomicGroupTypes: [
            (s) => [s.groupsTaxonomicTypes],
            (groupsTaxonomicTypes: TaxonomicFilterGroupType[]): TaxonomicFilterGroupType[] => [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ],
        ],
        sentimentCards: [
            (s) => [s.generations, s.activeFilters, s.intensityThreshold],
            (
                generations: SentimentGeneration[],
                activeFilters: Set<SentimentCategory>,
                intensityThreshold: number
            ): SentimentCard[] => {
                const cards: SentimentCard[] = []
                for (const gen of generations) {
                    const sentimentData = gen.sentiment
                    if (!sentimentData?.messages) {
                        continue
                    }

                    // Find the best card per active category per generation
                    const best: Record<string, { index: number; score: number; sentiment: MessageSentiment }> = {}

                    for (const [idx, msg] of Object.entries(sentimentData.messages)) {
                        if (!activeFilters.has(msg.label as SentimentCategory)) {
                            continue
                        }
                        // For neutral messages, skip the intensity threshold — neutral scores are
                        // inherently lower and the threshold is designed for positive/negative signals
                        if (msg.label !== 'neutral' && msg.score < intensityThreshold) {
                            continue
                        }
                        const prev = best[msg.label]
                        if (!prev || msg.score > prev.score) {
                            best[msg.label] = { index: Number(idx), score: msg.score, sentiment: msg }
                        }
                    }

                    for (const { index, sentiment } of Object.values(best)) {
                        cards.push({ generation: gen, messageIndex: index, sentiment })
                    }
                }
                return cards
            },
        ],
        /** Counts of displayable cards per sentiment category (best-per-generation, matching sentimentCards logic) */
        sentimentSummary: [
            (s) => [s.generations, s.intensityThreshold],
            (generations: SentimentGeneration[], intensityThreshold: number): Record<SentimentCategory, number> => {
                const counts: Record<SentimentCategory, number> = { positive: 0, negative: 0, neutral: 0 }
                for (const gen of generations) {
                    const sentimentData = gen.sentiment
                    if (!sentimentData?.messages) {
                        continue
                    }
                    // Use the same best-per-category-per-generation logic as sentimentCards
                    const best: Partial<Record<SentimentCategory, number>> = {}
                    for (const msg of Object.values(sentimentData.messages)) {
                        const label = msg.label as SentimentCategory
                        if (!(label in counts)) {
                            continue
                        }
                        if (label !== 'neutral' && msg.score < intensityThreshold) {
                            continue
                        }
                        const prev = best[label]
                        if (prev === undefined || msg.score > prev) {
                            best[label] = msg.score
                        }
                    }
                    for (const label of Object.keys(best) as SentimentCategory[]) {
                        counts[label]++
                    }
                }
                return counts
            },
        ],
        groupedSentimentCards: [
            (s) => [s.sentimentCards],
            (cards: SentimentCard[]): GroupedSentimentCard[] => {
                const groups = new Map<string, { grouped: GroupedSentimentCard; traceIds: Set<string> }>()
                const result: GroupedSentimentCard[] = []

                for (const card of cards) {
                    const text = getCardMessageText(card)
                    // Empty/unparseable messages get a unique key so they're never grouped
                    const key = text || `__unique__${card.generation.uuid}:${card.messageIndex}`
                    const existing = groups.get(key)
                    if (existing) {
                        existing.traceIds.add(card.generation.traceId)
                        existing.grouped.traceCount = existing.traceIds.size
                    } else {
                        const grouped: GroupedSentimentCard = {
                            card,
                            traceCount: 1,
                        }
                        groups.set(key, { grouped, traceIds: new Set([card.generation.traceId]) })
                        result.push(grouped)
                    }
                }

                return result
            },
        ],
        stillAnalyzing: [(s) => [s.generationsLoading], (generationsLoading: boolean): boolean => generationsLoading],
        showSentimentEvaluationOnboarding: [
            (s) => [
                s.hasLoadedSentimentEvaluations,
                s.hasSentimentEvaluations,
                s.hasLoadedOnce,
                s.generations,
                s.generationsLoading,
                s.generationsError,
                s.hasMore,
                s.autoLoadRounds,
            ],
            (
                hasLoadedSentimentEvaluations: boolean,
                hasSentimentEvaluations: boolean,
                hasLoadedOnce: boolean,
                generations: SentimentGeneration[],
                generationsLoading: boolean,
                generationsError: boolean,
                hasMore: boolean,
                autoLoadRounds: number
            ): boolean =>
                hasLoadedSentimentEvaluations &&
                hasLoadedOnce &&
                !hasSentimentEvaluations &&
                !generationsLoading &&
                !generationsError &&
                generations.length === 0 &&
                (!hasMore || autoLoadRounds >= MAX_AUTO_LOAD_ROUNDS),
        ],
    }),

    listeners(({ values, actions }) => {
        return {
            activate: () => {
                if (!values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            loadGenerationsSuccess: () => {
                actions.setHasMore(lastRawFetchCount >= GENERATIONS_PAGE_SIZE)
            },
            loadMoreGenerationsSuccess: () => {
                actions.setHasMore(lastRawFetchCount >= GENERATIONS_PAGE_SIZE)
            },
            toggleCardExpanded: ({ cardKey: key }) => {
                // Only track when expanding (key is now in the set), not collapsing
                if (!values.expandedCardIds.has(key)) {
                    return
                }
                const group = values.groupedSentimentCards.find((g) => cardKey(g.card) === key)
                if (!group) {
                    return
                }
                captureEngagementEvents(
                    'expanded',
                    group.card,
                    values.groupedSentimentCards,
                    values.activeFilters,
                    values.intensityThreshold
                )
            },
            trackTraceClicked: ({ card }) => {
                captureEngagementEvents(
                    'trace_clicked',
                    card,
                    values.groupedSentimentCards,
                    values.activeFilters,
                    values.intensityThreshold
                )
            },
        }
    }),

    subscriptions(({ actions, values }) => {
        let wasAnalyzing = false

        return {
            activeTab: (activeTab) => {
                if (activeTab === 'sentiment') {
                    actions.activate()
                }
            },
            dateFilter: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            shouldFilterTestAccounts: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            propertyFilters: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            stillAnalyzing: (stillAnalyzing: boolean) => {
                if (wasAnalyzing && !stillAnalyzing && values.activeTab === 'sentiment') {
                    const totalGenerations = values.generations.length
                    const cardCount = values.sentimentCards.length
                    const visibleCards = values.groupedSentimentCards.length

                    // Auto-load more generations if we don't have enough visible cards
                    const shouldAutoLoad =
                        visibleCards < MIN_VISIBLE_CARDS &&
                        values.hasMore &&
                        values.autoLoadRounds < MAX_AUTO_LOAD_ROUNDS

                    if ((totalGenerations === 0 || cardCount === 0) && !shouldAutoLoad) {
                        posthog.capture('llma sentiment empty state', {
                            reason: totalGenerations === 0 ? 'no_generations' : 'no_sentiment_results',
                            total_generations: totalGenerations,
                            sentiment_filter: Array.from(values.activeFilters).sort().join(','),
                            intensity_threshold: values.intensityThreshold,
                        })
                    }

                    if (shouldAutoLoad) {
                        actions.loadMoreGenerations()
                    }
                }
                wasAnalyzing = stillAnalyzing
            },
        }
    }),
])
