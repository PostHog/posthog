import { LLMTrace } from '~/queries/schema/schema-general'

import { IDLE_CAP_MS, buildSessionTimeline } from './buildSessionTimeline'
import { SessionTurn } from './extractSessionTurns'

function turn(offsetMs: number, latencySec: number): SessionTurn {
    return {
        trace: {
            id: `t-${offsetMs}`,
            createdAt: new Date(1_000_000_000_000 + offsetMs).toISOString(),
            totalLatency: latencySec,
        } as LLMTrace,
        isLoaded: true,
        newInputs: [],
        outputs: [],
        tools: [],
        errors: [],
    }
}

describe('buildSessionTimeline', () => {
    it('places the request behind a user-think lead-in, then the response after the AI latency', () => {
        const { turnRevealsMs, turnStartsMs, turnResponsesMs } = buildSessionTimeline([turn(0, 1)])
        expect(turnRevealsMs).toEqual([0]) // turn appears, user starts composing
        expect(turnStartsMs).toEqual([600]) // request lands after the 600ms user-think floor
        expect(turnResponsesMs).toEqual([1600]) // response 1s after the request
    })

    it('positions turns by elapsed time, splitting user-think, request, and response', () => {
        const { turnRevealsMs, turnStartsMs, turnResponsesMs, durationMs } = buildSessionTimeline([
            turn(0, 1),
            turn(2000, 0.5),
        ])
        expect(turnRevealsMs).toEqual([0, 1600]) // 2nd turn reveals when the 1st response lands
        expect(turnStartsMs).toEqual([600, 2600]) // 2nd user-think = 1000ms real gap after the 1st response
        expect(turnResponsesMs).toEqual([1600, 3200]) // 2nd think floored to 600ms
        expect(durationMs).toBe(3200)
    })

    it('caps long idle gaps between turns', () => {
        // 60s real gap collapses to IDLE_CAP_MS (measured from the prior response)
        const { turnStartsMs } = buildSessionTimeline([turn(0, 1), turn(61_000, 1)])
        expect(turnStartsMs[1]).toBe(1600 + IDLE_CAP_MS)
    })

    it('handles a single turn', () => {
        expect(buildSessionTimeline([turn(0, 2)])).toMatchObject({
            turnRevealsMs: [0],
            turnStartsMs: [600],
            turnResponsesMs: [2600],
            durationMs: 2600,
        })
    })

    it('returns empty for no turns', () => {
        expect(buildSessionTimeline([])).toEqual({
            turnRevealsMs: [],
            turnStartsMs: [],
            turnResponsesMs: [],
            durationMs: 0,
        })
    })
})
