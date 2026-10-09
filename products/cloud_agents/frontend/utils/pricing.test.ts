import type { CloudAgentRateCardApi } from '../generated/api.schemas'
import { describeBoxCost, formatCost, formatRate, formatSecondsAsHours, pricePerHourUsd } from './pricing'

const RATES: CloudAgentRateCardApi = { vcpu_hour_usd: '0.040', memory_gib_hour_usd: '0.013', version: 'test' }

describe('pricing', () => {
    test.each([
        [1, 2, 15, 'This box costs $0.066 per hour, about $0.02 for 15 minutes'],
        [1, 2, 60, 'This box costs $0.066 per hour, about $0.07 for 60 minutes'],
        [2, 4, 1, 'This box costs $0.132 per hour, about <$0.01 for 1 minute'],
        [4, 16, 15, 'This box costs $0.368 per hour, about $0.09 for 15 minutes'],
        [4, 16, 90, 'This box costs $0.368 per hour, about $0.55 for 90 minutes'],
        [8, 32, 30, 'This box costs $0.736 per hour, about $0.37 for 30 minutes'],
        [16, 64, 240, 'This box costs $1.472 per hour, about $5.89 for 240 minutes'],
        [16, 64, 60000, 'This box costs $1.472 per hour, about $1,472.00 for 60000 minutes'],
    ])('a %i vCPU, %i GiB box for %i minutes reads "%s"', (vcpu, memory_gib, minutes, expected) => {
        expect(describeBoxCost({ vcpu, memory_gib }, minutes, RATES)).toEqual(expected)
    })

    test.each([
        [4, 16, 0.368],
        [2, 8, 0.184],
        [8, 16, 0.528],
    ])('a %i vCPU, %i GiB box costs exactly %d per hour', (vcpu, memory_gib, expected) => {
        expect(pricePerHourUsd({ vcpu, memory_gib }, RATES)).toBe(expected)
    })

    test.each([
        ['0.1234', '$0.12'],
        ['0.005', '$0.01'],
        ['0.0049', '<$0.01'],
        ['0', '$0.00'],
        ['1234.5', '$1,234.50'],
        [null, '-'],
        ['not a number', '-'],
    ])('formatCost(%p) is %p', (value, expected) => {
        expect(formatCost(value)).toEqual(expected)
    })

    test.each([
        ['0.040', '$0.040'],
        [0.368, '$0.368'],
        [null, '-'],
    ])('formatRate(%p) is %p', (value, expected) => {
        expect(formatRate(value)).toEqual(expected)
    })

    test.each([
        ['5400', '1.50'],
        ['0', '0.00'],
        [null, '-'],
    ])('formatSecondsAsHours(%p) is %p', (value, expected) => {
        expect(formatSecondsAsHours(value)).toEqual(expected)
    })
})
