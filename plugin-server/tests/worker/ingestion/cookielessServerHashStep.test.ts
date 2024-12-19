import { UUID7 } from '../../../src/utils/utils'
import {
    bufferToSessionState,
    sessionStateToBuffer,
} from '../../../src/worker/ingestion/event-pipeline/cookielessServerHashStep'

describe('cookielessServerHashStep', () => {
    describe('sessionStateToBuffer', () => {
        it('should return a binary representation of the session state which can be converted back to the original', () => {
            const date = new Date('2024-12-17T10:50Z')
            const uuidRand = Buffer.from('0123456789ABCDEF0123', 'hex')
            const sessionId = new UUID7(date.getTime(), uuidRand)

            // check that the bytes are as expected
            const sessionStateBuf = sessionStateToBuffer({ sessionId, lastActivityTimestamp: date.getTime() })
            expect(sessionStateBuf.toString('hex')).toMatchInlineSnapshot(
                `"0193d43d2fc07123856789abcdef0123c02f3dd493010000"`
            )

            // make sure its reversible
            const sessionState = bufferToSessionState(sessionStateBuf)
            expect(sessionState.lastActivityTimestamp).toEqual(date.getTime())
            expect(sessionState.sessionId).toEqual(sessionId)
        })
    })
})
