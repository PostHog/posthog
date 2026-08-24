import { projectedWeeklyRecordings } from './ProjectedRecordings'

describe('projectedWeeklyRecordings', () => {
    it('scales weekly sessions by the sample rate', () => {
        expect(projectedWeeklyRecordings(1000, 30)).toEqual(300)
    })

    it('rounds to a whole number of recordings', () => {
        expect(projectedWeeklyRecordings(1001, 33)).toEqual(330)
    })

    it('clamps a rate above 100 so it never projects more than the session volume', () => {
        expect(projectedWeeklyRecordings(1000, 150)).toEqual(1000)
    })

    it('clamps a negative rate to zero', () => {
        expect(projectedWeeklyRecordings(1000, -10)).toEqual(0)
    })
})
