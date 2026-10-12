import { HOMEPAGE_SUGGESTION_TOPICS } from './suggestionTopics'

describe('HOMEPAGE_SUGGESTION_TOPICS', () => {
    const cardTopics = HOMEPAGE_SUGGESTION_TOPICS.filter((topic) => (topic.variant ?? 'cards') === 'cards')

    // Every card topic renders the same number of cards, so toggling a badge never changes the grid height
    it.each(cardTopics.map((topic) => [topic.key, topic]))('%s has exactly 4 card suggestions', (_, topic) => {
        expect(topic.suggestions).toHaveLength(4)
    })

    it('pairs every fill-in prompt with a hint and gives every complete prompt none', () => {
        const suggestions = HOMEPAGE_SUGGESTION_TOPICS.flatMap((topic) => topic.suggestions)
        for (const suggestion of suggestions) {
            expect(!!suggestion.requiresUserInput).toBe(!!suggestion.hint)
        }
    })
})
