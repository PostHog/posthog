import type { BetsEvidenceApi, BetsWorkApi } from '../generated/api.schemas'
import { ideaEvidence, ideaReason, ideaReportRest } from './ideas'

function idea(patch: Partial<BetsWorkApi>): BetsWorkApi {
    return { summary: '', evidence: [], ...patch } as BetsWorkApi
}

function evidence(kind: BetsEvidenceApi['kind'], label: string): BetsEvidenceApi {
    return { kind, label, url: `/${label}` }
}

describe('ideas', () => {
    it.each([
        [
            'Supported. People who see a sample upload twice as often. A second line.',
            'People who see a sample upload twice as often.',
            'A second line.',
        ],
        [
            'Not supported. Uploads finish in 2.1 s. People leave before upload.',
            'Uploads finish in 2.1 s.',
            'People leave before upload.',
        ],
        ['not supported: Few people use the coupon field.', 'Few people use the coupon field.', ''],
        ['People who see a sample upload more.', 'People who see a sample upload more.', ''],
    ])('splits the summary %#', (summary, reason, rest) => {
        const item = idea({ summary })
        expect(ideaReason(item)).toBe(reason)
        expect(ideaReportRest(item)).toBe(rest)
    })

    it('keeps PostHog evidence only, replays first, then insights and charts in their order', () => {
        const item = idea({
            evidence: [
                evidence('link', 'repo#15'),
                evidence('chart', 'chart'),
                evidence('experiment', 'experiment'),
                evidence('insight', 'insight'),
                evidence('error', 'error'),
                evidence('replay', 'replay'),
                evidence('link', 'report'),
            ],
        })
        expect(ideaEvidence(item).map((entry) => entry.label)).toEqual([
            'replay',
            'chart',
            'insight',
            'error',
            'experiment',
        ])
    })
})
