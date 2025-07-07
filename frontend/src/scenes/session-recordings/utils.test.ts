import { quickEmojis } from 'scenes/session-recordings/player/commenting/playerFrameCommentOverlayLogic'
import { isSingleEmoji } from 'scenes/session-recordings/utils'

describe('session recording utils', () => {
    quickEmojis.forEach((quickEmoji) => {
        it(`can check ${quickEmoji} is a single emoji`, () => {
            expect(isSingleEmoji(quickEmoji)).toBe(true)
        })
        it(`can check ${quickEmoji}${quickEmoji} is not a single emoji`, () => {
            expect(isSingleEmoji(`${quickEmoji}${quickEmoji}`)).toBe(false)
        })
    })
})
