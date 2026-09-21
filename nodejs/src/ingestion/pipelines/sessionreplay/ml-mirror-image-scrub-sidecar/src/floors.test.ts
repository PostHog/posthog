import { CODE_FLOOR, FACE_FLOOR, vacuousDetectors } from './floors.ts'
import { limitsFromEnv, planScales } from './scale-plan.ts'

describe('vacuousDetectors', () => {
    // The bound is the readable floor with a four times margin, on the stored size. Each case sits
    // one px on one side of one bound, so a threshold that drifts to the wrong side of a floor
    // fails exactly one row.
    const faceBound = Math.ceil(FACE_FLOOR.readableAt / 4)
    const codeBound = Math.ceil((CODE_FLOOR.readableAt * Math.sqrt(0.1 / 2.07)) / 4)
    const CASES: [string, number, number, boolean, boolean][] = [
        ['a favicon stored at 4 px', 4, 4, true, true],
        ['a short side one below the face bound', 100, faceBound - 1, true, false],
        ['a short side at the face bound', 100, faceBound, false, false],
        ['a long side one below the code bound', codeBound - 1, codeBound - 1, false, true],
        ['a long side at the code bound', codeBound, codeBound, false, false],
        ['a desktop frame stored at 298x168', 298, 168, false, false],
    ]

    it.each(CASES)('for %s', (_case, width, height, face, code) => {
        expect(vacuousDetectors({ width, height })).toEqual({ face, code })
    })

    // What the bound means at the frame, under the deployed plan: an icon skips both detectors,
    // and an avatar of 64 px, which the plan stores at 16 px, still has its face detected.
    it.each([
        ['a 20 px icon', 20, 20, true, true],
        ['a 64 px avatar', 64, 64, false, false],
        ['a 63 px square', 63, 63, false, true],
        ['a 100 px square', 100, 100, false, false],
    ])('under the deployed plan, %s', (_case, width, height, face, code) => {
        const plan = planScales({ width, height }, limitsFromEnv())

        expect(vacuousDetectors(plan.stored)).toEqual({ face, code })
    })
})
