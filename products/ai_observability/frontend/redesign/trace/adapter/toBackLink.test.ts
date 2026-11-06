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

    it.each([
        ['evaluation', 'Back to evaluation'],
        ['prompt', 'Back to prompt'],
        ['constructor', 'Back'],
        [undefined, 'Back'],
    ])('follows an internal back_url with back_to %s', (backTo, label) => {
        const backUrl = '/prompt-management/prompts/p1?tab=usage&search=invoice'

        expect(toBackLink({ back_to: backTo, back_url: backUrl })).toEqual({ label, href: backUrl })
    })

    it('follows a back_url under a project prefix', () => {
        const backUrl = '/project/1/ai-evals/evaluations/e1'

        expect(toBackLink({ back_url: backUrl }).href).toBe(backUrl)
    })

    it.each([
        'https://x',
        '//x',
        '/\\x',
        '/x\\y',
        '/\t/x',
        'x',
        '',
        5,
        '/api/integrations/authorize?next=/x',
        '/x/../api/y',
        '/logout',
        '/ai-observability/../logout',
        '/ai-observabilityx/traces',
        '/project/1/dashboard',
        '/%2e%2e/api/y',
    ])('ignores the back_url %s', (backUrl) => {
        expect(toBackLink({ back_to: 'generations', back_url: backUrl, date_from: '-7d' })).toEqual({
            label: 'Back to generations',
            href: '/ai-observability/generations?date_from=-7d',
        })
    })
})
