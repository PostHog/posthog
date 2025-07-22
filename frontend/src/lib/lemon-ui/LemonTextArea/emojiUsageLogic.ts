import { actions, kea, reducers, path, selectors } from 'kea'
import { now } from 'lib/dayjs'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { emojiUsageLogicType } from './emojiUsageLogicType'

export const defaultQuickEmojis = ['💖', '👍', '🤔', '👎', '🌶️']

export const emojiUsageLogic = kea<emojiUsageLogicType>([
    path(['lib', 'lemon-ui', 'LemonTextArea', 'emojiUsage', 'logic']),
    actions({
        emojiUsed: (emoji: string) => ({ emoji }),
    }),
    reducers({
        usedEmojis: [
            {} as Record<string, number[]>,
            { persist: true },
            {
                emojiUsed: (state, { emoji }) => {
                    const currentTime = now().valueOf()
                    const thirtyDaysAgo = currentTime - 30 * 24 * 60 * 60 * 1000

                    const newState = { ...state, [emoji]: state[emoji] || [] }
                    newState[emoji] = [...newState[emoji], currentTime]

                    newState[emoji] = newState[emoji].filter((timestamp: number) => timestamp > thirtyDaysAgo)

                    if (newState[emoji].length === 0) {
                        delete newState[emoji]
                    } else {
                        // Limit to max 10 timestamps per emoji to prevent memory issues
                        if (newState[emoji].length > 10) {
                            newState[emoji] = newState[emoji].slice(-10)
                        }
                    }

                    return newState
                },
            },
        ],
    }),
    selectors({
        favouriteEmojis: [
            (s) => [s.usedEmojis],
            (usedEmojis): string[] => {
                // Get user's favorite emojis sorted by usage count
                const userFavorites = Object.entries(usedEmojis)
                    .map(([emoji, timestamps]) => ({
                        emoji,
                        count: timestamps.length,
                    }))
                    .sort((a, b) => b.count - a.count) // Sort by usage count descending
                    .slice(0, 5) // Take top 5
                    .map(({ emoji }) => emoji) // Extract just the emoji strings

                // If we have fewer than 5 favorites, fill with quickEmojis (avoiding duplicates)
                if (userFavorites.length < 5) {
                    const remainingSlots = 5 - userFavorites.length
                    const availableQuickEmojis = defaultQuickEmojis.filter((emoji) => !userFavorites.includes(emoji))
                    const fillEmojis = availableQuickEmojis.slice(0, remainingSlots)
                    return [...userFavorites, ...fillEmojis]
                }

                return userFavorites
            },
        ],
    }),
    permanentlyMount(),
])
