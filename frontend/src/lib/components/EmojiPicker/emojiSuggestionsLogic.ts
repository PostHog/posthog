import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import * as api from '~/generated/core/api'
import { EmojiSuggestionApi } from '~/generated/core/api.schemas'

const MIN_QUERY_LENGTH = 3
const MAX_QUERY_LENGTH = 64
const DEBOUNCE_MS = 200
const REQUEST_TIMEOUT_MS = 2500

type EmojiSuggestionsLogicType = MakeLogicType<
    {
        currentProjectId: number | null
        featureFlags: FeatureFlagsSet
        query: string
        suggestionsByQuery: Record<string, EmojiSuggestionApi[]>
        failedQuery: string | null
        isSearchable: boolean
        cachedSuggestions: EmojiSuggestionApi[] | null
        suggestions: EmojiSuggestionApi[]
        loading: boolean
    },
    {
        setQuery: (query: string) => { query: string }
        setSuggestions: (
            query: string,
            suggestions: EmojiSuggestionApi[]
        ) => { query: string; suggestions: EmojiSuggestionApi[] }
        setSuggestionsFailed: (query: string) => { query: string }
    },
    EmojiSuggestionsLogicProps
>

export interface EmojiSuggestionsLogicProps {
    pickerKey: string
}

export const emojiSuggestionsLogic = kea<EmojiSuggestionsLogicType>([
    props({} as EmojiSuggestionsLogicProps),
    key((props) => props.pickerKey),
    path((key) => ['lib', 'components', 'EmojiPicker', 'emojiSuggestionsLogic', key]),
    connect(() => ({ values: [projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']] })),
    actions({
        setQuery: (query: string) => ({ query: query.trim() }),
        setSuggestions: (query: string, suggestions: EmojiSuggestionApi[]) => ({ query, suggestions }),
        setSuggestionsFailed: (query: string) => ({ query }),
    }),
    reducers({
        query: ['', { setQuery: (_, { query }) => query }],
        suggestionsByQuery: [
            {} as Record<string, EmojiSuggestionApi[]>,
            { setSuggestions: (state, { query, suggestions }) => ({ ...state, [query]: suggestions }) },
        ],
        // Failures are not cached, so the same query can try again later.
        failedQuery: [null as string | null, { setQuery: () => null, setSuggestionsFailed: (_, { query }) => query }],
    }),
    selectors({
        isSearchable: [
            (s) => [s.query, s.currentProjectId, s.featureFlags],
            (query, currentProjectId, featureFlags): boolean => {
                if (!featureFlags[FEATURE_FLAGS.EMOJI_RELATED_SEARCH]) {
                    return false
                }
                // The endpoint counts characters, so count code points and not UTF-16 units.
                const length = [...query].length
                return !!currentProjectId && length >= MIN_QUERY_LENGTH && length <= MAX_QUERY_LENGTH
            },
        ],
        cachedSuggestions: [
            (s) => [s.query, s.suggestionsByQuery],
            (query, suggestionsByQuery): EmojiSuggestionApi[] | null =>
                Object.hasOwn(suggestionsByQuery, query) ? suggestionsByQuery[query] : null,
        ],
        suggestions: [(s) => [s.cachedSuggestions], (cachedSuggestions) => cachedSuggestions ?? []],
        loading: [
            (s) => [s.query, s.isSearchable, s.cachedSuggestions, s.failedQuery],
            (query, isSearchable, cachedSuggestions, failedQuery): boolean =>
                isSearchable && cachedSuggestions === null && query !== failedQuery,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setQuery: async ({ query }, breakpoint) => {
            if (!values.isSearchable || values.cachedSuggestions !== null) {
                return
            }
            await breakpoint(DEBOUNCE_MS)
            cache.pendingQueries ??= new Set<string>()
            if (cache.pendingQueries.has(query)) {
                return
            }
            cache.pendingQueries.add(query)
            const controller = new AbortController()
            cache.disposables.add(
                () => {
                    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
                    return () => {
                        window.clearTimeout(timeout)
                        controller.abort()
                    }
                },
                `request:${query}`,
                { pauseOnPageHidden: false }
            )
            try {
                const response = await api.emojiSearchSuggestRetrieve(
                    String(values.currentProjectId),
                    { query },
                    { signal: controller.signal }
                )
                actions.setSuggestions(query, response.suggestions)
            } catch {
                if (!cache.disposables.isDisposed && query === values.query) {
                    actions.setSuggestionsFailed(query)
                }
            } finally {
                cache.pendingQueries.delete(query)
                cache.disposables.dispose(`request:${query}`)
            }
        },
    })),
])
