import { toBackLink } from './toBackLink'

describe('toBackLink', () => {
    it.each([
        [
            'the traces list by default, keeping its filters but not the search',
            { date_from: '-7d', event: 'gen-1', search: 'invoice' },
            '/ai-observability/traces?date_from=-7d',
        ],
        [
            'the generations list when opened from it',
            { back_to: 'generations', date_from: '-7d', tab: 'evals', search: 'invoice' },
            '/ai-observability/generations?date_from=-7d',
        ],
        [
            'the reviews tab when opened from reviews',
            { back_to: 'reviews' },
            '/ai-observability/reviews?human_reviews_tab=reviews',
        ],
        [
            'the review queue when opened from one',
            { back_to: 'reviews', queue_id: 'queue-1', search: 'invoice' },
            '/ai-observability/reviews?queue_id=queue-1',
        ],
    ])('goes back to %s', (_name, searchParams, expected) => {
        expect(toBackLink(searchParams).href).toBe(expected)
    })
})
