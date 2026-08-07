import { MakeLogicType, actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import type { LemonSelectOption } from 'lib/lemon-ui/LemonSelect'

import { groupsModel } from '~/models/groupsModel'

import type { AnyPropertyFilter } from '../../../../frontend/src/types'
import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import type { AIObservabilityTabId } from '../aiObservabilitySharedLogic'
import type { EvaluationApi } from '../generated/api.schemas'
import { sentimentEvaluationAvailabilityLogic } from '../sentimentEvaluationAvailabilityLogic'
import { fetchSentimentGenerationsPage, type SentimentCategory, type SentimentGeneration } from '../sentimentQueries'
import type { MessageSentiment } from '../sentimentResults'
import { extractContentText } from '../sentimentUtils'

export type { SentimentGeneration, SentimentCategory } from '../sentimentQueries'

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

let lastPageHasMore = false
let nextGenerationsOffset = 0

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilitySentimentLogicValues {
    activeTab: AIObservabilityTabId // aiObservabilitySharedLogic
    dateFilter: {
        dateFrom: string | null
        dateTo: string | null
    } // aiObservabilitySharedLogic
    propertyFilters: AnyPropertyFilter[] // aiObservabilitySharedLogic
    shouldFilterTestAccounts: boolean // aiObservabilitySharedLogic
    groupsTaxonomicTypes: TaxonomicFilterGroupType[] // groupsModel
    hasLoadedSentimentEvaluations: boolean // sentimentEvaluationAvailabilityLogic
    hasSentimentEvaluations: boolean // sentimentEvaluationAvailabilityLogic
    sentimentEvaluations: EvaluationApi[] // sentimentEvaluationAvailabilityLogic
    sentimentEvaluationsLoading: boolean // sentimentEvaluationAvailabilityLogic
    activeFilters: Set<SentimentCategory>
    evaluationId: string | null
    evaluationOptions: LemonSelectOption<string | null>[]
    expandedCardIds: Set<string>
    generations: SentimentGeneration[]
    generationsError: boolean
    generationsLoading: boolean
    groupedSentimentCards: GroupedSentimentCard[]
    hasLoadedOnce: boolean
    hasMore: boolean
    intensityThreshold: number
    sentimentCards: SentimentCard[]
    sentimentSummary: Record<SentimentCategory, number>
    showSentimentEvaluationOnboarding: boolean
    stillAnalyzing: boolean
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilitySentimentLogicActions {
    activate: () => {
        value: true
    }
    loadGenerations: ({ forceRefresh }?: { forceRefresh?: boolean }) => {
        forceRefresh?: boolean
    }
    loadGenerationsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadGenerationsSuccess: (
        generations: SentimentGeneration[],
        payload?: {
            forceRefresh?: boolean
        }
    ) => {
        generations: SentimentGeneration[]
        payload?: {
            forceRefresh?: boolean
        }
    }
    loadMoreGenerations: () => {
        value: true
    }
    loadMoreGenerationsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreGenerationsSuccess: (
        generations: SentimentGeneration[],
        payload?: {
            value: true
        }
    ) => {
        generations: SentimentGeneration[]
        payload?: {
            value: true
        }
    }
    setEvaluationId: (evaluationId: string | null) => {
        evaluationId: string | null
    }
    setHasMore: (hasMore: boolean) => {
        hasMore: boolean
    }
    setIntensityThreshold: (intensityThreshold: number) => {
        intensityThreshold: number
    }
    toggleCardExpanded: (cardKey: string) => {
        cardKey: string
    }
    toggleSentimentCategory: (category: SentimentCategory) => {
        category: SentimentCategory
    }
    trackTraceClicked: (card: SentimentCard) => {
        card: SentimentCard
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface aiObservabilitySentimentLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        taxonomicGroupTypes: (groupsTaxonomicTypes: TaxonomicFilterGroupType[]) => TaxonomicFilterGroupType[]
        evaluationOptions: (sentimentEvaluations: EvaluationApi[]) => LemonSelectOption<string | null>[]
        sentimentCards: (
            generations: SentimentGeneration[],
            activeFilters: Set<SentimentCategory>,
            intensityThreshold: number
        ) => SentimentCard[]
        sentimentSummary: (
            generations: SentimentGeneration[],
            intensityThreshold: number
        ) => Record<SentimentCategory, number>
        groupedSentimentCards: (sentimentCards: SentimentCard[]) => GroupedSentimentCard[]
        stillAnalyzing: (generationsLoading: boolean) => boolean
        showSentimentEvaluationOnboarding: (
            hasLoadedSentimentEvaluations: boolean,
            hasSentimentEvaluations: boolean,
            hasLoadedOnce: boolean,
            generations: SentimentGeneration[],
            generationsLoading: boolean,
            generationsError: boolean,
            hasMore: boolean
        ) => boolean
    }
}

export type aiObservabilitySentimentLogicType = MakeLogicType<
    aiObservabilitySentimentLogicValues,
    aiObservabilitySentimentLogicActions,
    AIObservabilitySentimentLogicProps,
    aiObservabilitySentimentLogicMeta
>

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
            [
                'hasLoadedSentimentEvaluations',
                'hasSentimentEvaluations',
                'sentimentEvaluations',
                'sentimentEvaluationsLoading',
            ],
        ],
    })),

    actions({
        activate: true,
        toggleSentimentCategory: (category: SentimentCategory) => ({ category }),
        setEvaluationId: (evaluationId: string | null) => ({ evaluationId }),
        setIntensityThreshold: (intensityThreshold: number) => ({ intensityThreshold }),
        toggleCardExpanded: (cardKey: string) => ({ cardKey }),
        loadMoreGenerations: true,
        setHasMore: (hasMore: boolean) => ({ hasMore }),
        trackTraceClicked: (card: SentimentCard) => ({ card }),
    }),

    reducers({
        activeFilters: [
            new Set<SentimentCategory>(['negative']) as Set<SentimentCategory>,
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
        evaluationId: [
            null as string | null,
            {
                setEvaluationId: (_, { evaluationId }) => evaluationId,
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
                loadGenerations: async ({ forceRefresh }: { forceRefresh?: boolean } = {}, breakpoint) => {
                    const page = await fetchSentimentGenerationsPage(values, 0, forceRefresh)
                    // The query is slow enough that toggling filters twice can leave two requests in
                    // flight — drop this one if a newer load started while it was running
                    breakpoint()
                    lastPageHasMore = page.hasMore
                    nextGenerationsOffset = page.rawCount
                    return page.generations
                },
                loadMoreGenerations: async () => {
                    const existing = values.generations
                    const page = await fetchSentimentGenerationsPage(values, nextGenerationsOffset)
                    lastPageHasMore = page.hasMore
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
        evaluationOptions: [
            (s) => [s.sentimentEvaluations],
            (sentimentEvaluations: EvaluationApi[]): LemonSelectOption<string | null>[] => [
                { value: null, label: 'All evaluations' },
                ...sentimentEvaluations.map((evaluation) => ({
                    value: evaluation.id,
                    label: evaluation.name,
                })),
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
                        if (msg.score < intensityThreshold) {
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
                const counts: Record<SentimentCategory, number> = { negative: 0, positive: 0 }
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
                        if (msg.score < intensityThreshold) {
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
            ],
            (
                hasLoadedSentimentEvaluations: boolean,
                hasSentimentEvaluations: boolean,
                hasLoadedOnce: boolean,
                generations: SentimentGeneration[],
                generationsLoading: boolean,
                generationsError: boolean,
                hasMore: boolean
            ): boolean =>
                hasLoadedSentimentEvaluations &&
                hasLoadedOnce &&
                !hasSentimentEvaluations &&
                !generationsLoading &&
                !generationsError &&
                generations.length === 0 &&
                !hasMore,
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
                actions.setHasMore(lastPageHasMore)
            },
            loadMoreGenerationsSuccess: () => {
                actions.setHasMore(lastPageHasMore)
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
            activeFilters: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            evaluationId: () => {
                if (values.hasLoadedOnce) {
                    actions.loadGenerations()
                }
            },
            stillAnalyzing: (stillAnalyzing: boolean) => {
                if (wasAnalyzing && !stillAnalyzing && values.activeTab === 'sentiment') {
                    const totalGenerations = values.generations.length
                    const cardCount = values.sentimentCards.length

                    if (totalGenerations === 0 || cardCount === 0) {
                        posthog.capture('llma sentiment empty state', {
                            reason: totalGenerations === 0 ? 'no_generations' : 'no_sentiment_results',
                            total_generations: totalGenerations,
                            sentiment_filter: Array.from(values.activeFilters).sort().join(','),
                            intensity_threshold: values.intensityThreshold,
                        })
                    }
                }
                wasAnalyzing = stillAnalyzing
            },
        }
    }),
])
