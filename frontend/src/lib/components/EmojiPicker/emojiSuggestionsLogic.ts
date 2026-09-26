import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { emojiSearchSuggestCreate } from '~/generated/core/api'
import { EmojiSuggestionApi } from '~/generated/core/api.schemas'

type EmojiSuggestionsLogicProps = {
    query: string
    projectId: number
}

type EmojiSuggestionsLogicType = MakeLogicType<
    { suggestions: EmojiSuggestionApi[]; loading: boolean },
    {
        loadSuggestions: () => { value: true }
        setSuggestions: (suggestions: EmojiSuggestionApi[]) => { suggestions: EmojiSuggestionApi[] }
    },
    EmojiSuggestionsLogicProps
>

export const emojiSuggestionsLogic = kea<EmojiSuggestionsLogicType>([
    path(['lib', 'components', 'EmojiPicker', 'emojiSuggestionsLogic']),
    props({} as EmojiSuggestionsLogicProps),
    key(({ query, projectId }) => `${projectId}:${query}`),
    actions({
        loadSuggestions: true,
        setSuggestions: (suggestions: EmojiSuggestionApi[]) => ({ suggestions }),
    }),
    reducers({
        suggestions: [[] as EmojiSuggestionApi[], { setSuggestions: (_, { suggestions }) => suggestions }],
        loading: [true, { setSuggestions: () => false }],
    }),
    listeners(({ actions, props }) => ({
        loadSuggestions: async (_, breakpoint) => {
            await breakpoint(200)
            const controller = new AbortController()
            const timeout = window.setTimeout(() => controller.abort(), 800)
            try {
                const response = await emojiSearchSuggestCreate(
                    String(props.projectId),
                    { query: props.query },
                    { signal: controller.signal }
                )
                actions.setSuggestions(response.suggestions)
            } catch {
                actions.setSuggestions([])
            } finally {
                window.clearTimeout(timeout)
            }
        },
    })),
    afterMount(({ actions }) => actions.loadSuggestions()),
])
