import { findCampaignSuggestions, levenshteinDistance, similarityScore } from './stringSimilarity'

describe('stringSimilarity', () => {
    describe('levenshteinDistance', () => {
        it.each([
            ['', '', 0],
            ['a', 'a', 0],
            ['abc', 'abc', 0],
            ['a', 'b', 1],
            ['abc', 'abd', 1],
            ['abc', 'abcd', 1],
            ['abcd', 'abc', 1],
            ['kitten', 'sitting', 3],
            ['saturday', 'sunday', 3],
        ])('distance between "%s" and "%s" should be %i', (a, b, expected) => {
            expect(levenshteinDistance(a, b)).toBe(expected)
        })
    })

    describe('similarityScore', () => {
        it.each([
            ['brand', 'brand', 1],
            ['Brand', 'brand', 1],
            ['BRAND', 'brand', 1],
            ['', '', 1], // empty strings are identical
            ['a', '', 0],
            ['', 'b', 0],
        ])('score between "%s" and "%s" should be %d', (a, b, expected) => {
            expect(similarityScore(a, b)).toBe(expected)
        })

        it('should give bonus for substring match', () => {
            const withSubstring = similarityScore('summer', 'summer_sale_2024')
            const withoutSubstring = similarityScore('summer', 'winter_sale_2024')
            expect(withSubstring).toBeGreaterThan(withoutSubstring)
        })

        it('should return score between 0 and 1', () => {
            const score = similarityScore('completely', 'different')
            expect(score).toBeGreaterThanOrEqual(0)
            expect(score).toBeLessThanOrEqual(1)
        })
    })

    describe('findCampaignSuggestions', () => {
        const campaigns = [
            { name: 'Summer Sale 2024', id: '123456' },
            { name: 'Winter Campaign', id: '789012' },
            { name: 'Brand Awareness', id: '345678' },
            { name: 'Black Friday', id: '901234' },
        ]

        it('should return empty array for empty input', () => {
            expect(findCampaignSuggestions('', campaigns)).toEqual([])
            expect(findCampaignSuggestions('  ', campaigns)).toEqual([])
        })

        it('should return empty array for empty campaigns', () => {
            expect(findCampaignSuggestions('test', [])).toEqual([])
        })

        it('should find exact match by name', () => {
            const results = findCampaignSuggestions('Brand Awareness', campaigns)
            expect(results[0].name).toBe('Brand Awareness')
            expect(results[0].score).toBe(1)
        })

        it('should find exact match by id', () => {
            const results = findCampaignSuggestions('123456', campaigns)
            expect(results[0].id).toBe('123456')
            expect(results[0].score).toBe(1)
            expect(results[0].matchedBy).toBe('id')
        })

        it('should find partial match by name', () => {
            const results = findCampaignSuggestions('summer', campaigns)
            expect(results[0].name).toBe('Summer Sale 2024')
            expect(results[0].matchedBy).toBe('name')
        })

        it('should return top N results', () => {
            const results = findCampaignSuggestions('a', campaigns, 2)
            expect(results.length).toBeLessThanOrEqual(2)
        })

        it('should sort by score descending', () => {
            const results = findCampaignSuggestions('brand', campaigns)
            for (let i = 1; i < results.length; i++) {
                expect(results[i - 1].score).toBeGreaterThanOrEqual(results[i].score)
            }
        })

        it('should match by id when id is more similar', () => {
            const results = findCampaignSuggestions('12345', campaigns)
            expect(results[0].matchedBy).toBe('id')
        })

        it('should match by name when name is more similar', () => {
            const results = findCampaignSuggestions('Black', campaigns)
            expect(results[0].matchedBy).toBe('name')
            expect(results[0].name).toBe('Black Friday')
        })
    })
})
