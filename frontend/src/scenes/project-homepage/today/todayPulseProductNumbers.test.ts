import { productNumberKind, productNumberPinReason } from './todayPulseProductNumbers'

describe('todayPulseProductNumbers', () => {
    test.each([
        ['experiment:7', 'experiment', "Experiments can't be pinned"],
        ['evaluation:0195-ab', 'evaluation', "Evaluations can't be pinned"],
        ['insight:abc', null, null],
        ['signup_event', null, null],
    ])('treats %s as %s', (key, kind, reason) => {
        expect([productNumberKind(key), productNumberPinReason(key)]).toEqual([kind, reason])
    })
})
