import { defaultQuickEmojis } from 'lib/lemon-ui/LemonTextArea/emojiUsageLogic'
import { isSingleEmoji } from 'scenes/session-recordings/utils'

describe('session recording utils', () => {
    defaultQuickEmojis.forEach((quickEmoji) => {
        it(`can check ${quickEmoji} is a single emoji`, () => {
            expect(isSingleEmoji(quickEmoji)).toBe(true)
        })
        it(`can check ${quickEmoji}${quickEmoji} is not a single emoji`, () => {
            expect(isSingleEmoji(`${quickEmoji}${quickEmoji}`)).toBe(false)
        })
    })
})
