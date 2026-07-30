import { ReputationMetrics, ReputationState, classifyReputation } from './classifier'

describe('classifyReputation', () => {
    it.each<[string, ReputationMetrics, ReputationState]>([
        ['zero sends is insufficient data', { sent: 0, bounced: 0, complained: 0 }, 'insufficient_data'],
        [
            'below min sends is insufficient data even at terrible rates',
            { sent: 50, bounced: 25, complained: 5 },
            'insufficient_data',
        ],
        ['healthy below all thresholds', { sent: 1000, bounced: 5, complained: 0 }, 'healthy'],
        ['warning at the bounce warning threshold (inclusive)', { sent: 1000, bounced: 20, complained: 0 }, 'warning'],
        [
            'warning at the complaint warning threshold (inclusive)',
            { sent: 1000, bounced: 0, complained: 1 },
            'warning',
        ],
        ['critical at the bounce critical threshold', { sent: 1000, bounced: 50, complained: 0 }, 'critical'],
        ['critical at the complaint critical threshold', { sent: 1000, bounced: 0, complained: 5 }, 'critical'],
        ['critical wins over warning when signals disagree', { sent: 1000, bounced: 20, complained: 5 }, 'critical'],
    ])('%s', (_name, metrics, expected) => {
        expect(classifyReputation(metrics).state).toEqual(expected)
    })

    it('reports the computed rates', () => {
        const { bounceRate, complaintRate } = classifyReputation({ sent: 200, bounced: 10, complained: 1 })
        expect(bounceRate).toBeCloseTo(0.05)
        expect(complaintRate).toBeCloseTo(0.005)
    })
})
