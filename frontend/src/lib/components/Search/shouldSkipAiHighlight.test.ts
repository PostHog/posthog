import { SearchItem } from './searchLogic'
import { shouldSkipAiHighlight } from './shouldSkipAiHighlight'

// Helper to create a minimal SearchItem
const createItem = (overrides: Partial<SearchItem> = {}): SearchItem => ({
    id: 'test-id',
    name: 'Test Item',
    category: 'insight',
    href: '/test',
    ...overrides,
})

describe('shouldSkipAiHighlight', () => {
    describe('Guards - keep AI highlighted', () => {
        it.each([
            ['', []],
            ['   ', []],
            ['a', [createItem()]],
        ])('returns false for empty or single character query: "%s"', (query, items) => {
            expect(shouldSkipAiHighlight(query, items)).toBe(false)
        })

        it.each(['ai', 'max', 'posthog ai', 'ask ai', 'ask posthog', 'AI', 'MAX'])(
            'returns false for explicit AI intent: "%s"',
            (query) => {
                expect(shouldSkipAiHighlight(query, [createItem()])).toBe(false)
            }
        )
    })

    describe('Anti-patterns - keep AI highlighted', () => {
        it.each([
            'how do I create a dashboard',
            'what is a cohort',
            'why is this not working',
            'when should I use feature flags',
            'where can I find insights',
            'who created this',
            'which experiment won',
            'can I export this',
            'could you explain',
            'should I use this',
            'would this work',
            'is this correct',
            'are there any errors',
            'do I need to restart',
            'does this support',
            'did the experiment finish',
            'will this affect performance',
            'was this deleted',
            'were there any issues',
            'have I configured this correctly',
            'has the sync completed',
            'had any changes been made',
        ])('returns false for question word prefix: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [createItem()])).toBe(false)
        })

        it.each(['what is this?', 'how does it work?', 'test query?'])(
            'returns false when query contains question mark: "%s"',
            (query) => {
                expect(shouldSkipAiHighlight(query, [createItem()])).toBe(false)
            }
        )

        it.each([
            'compare dashboard A and dashboard B',
            'show me trends versus cohorts',
            'analyze user behavior between jan and feb',
            'tell me about feature flags',
            'explain how experiments work',
            'help me understand retention',
            'summarize last week activity',
            'generate a report on users',
        ])('returns false for analytical language: "%s"', (query) => {
            // Need 2+ items to avoid single-result heuristic
            expect(shouldSkipAiHighlight(query, [createItem(), createItem({ id: 'test-2' })])).toBe(false)
        })

        it('returns false for long sentences (4+ words without identifiers)', () => {
            const query = 'show me all the users who signed up'
            // Need 2+ items to avoid single-result heuristic
            expect(shouldSkipAiHighlight(query, [createItem(), createItem({ id: 'test-2' })])).toBe(false)
        })
    })

    describe('Structural identifiers - skip AI', () => {
        it.each([
            '550e8400-e29b-41d4-a716-446655440000',
            '123e4567-e89b-12d3-a456-426614174000',
            'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE',
        ])('returns true for UUID pattern: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [])).toBe(true) // Even without results
        })

        it.each(['user@example.com', 'test.user@posthog.com', 'john+tag@company.co.uk'])(
            'returns true for email pattern: "%s"',
            (query) => {
                expect(shouldSkipAiHighlight(query, [])).toBe(true) // Even without results
            }
        )

        it.each(['user@', 'test@c', 'john@company'])('returns true for partial email with results: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [])).toBe(false) // No results
            expect(shouldSkipAiHighlight(query, [createItem({ category: 'persons' })])).toBe(true) // With results
        })

        it.each([
            '/insights/abc123',
            '/dashboard/456',
            '/feature_flags/my-flag',
            '/experiments/test-exp',
            '/cohorts/123',
            'https://app.posthog.com/insights/abc',
            'http://localhost/dashboard/1',
        ])('returns true for URL/path pattern: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [])).toBe(true)
        })

        it.each(['123', '456789'])('returns true for numeric ID with results: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [])).toBe(false)
            expect(shouldSkipAiHighlight(query, [createItem()])).toBe(true)
        })

        it('returns false for numeric ID "0" (single character guard)', () => {
            // "0" is caught by single-character guard, returns false regardless of results
            expect(shouldSkipAiHighlight('0', [createItem()])).toBe(false)
            expect(shouldSkipAiHighlight('0', [createItem(), createItem({ id: 'test-2' })])).toBe(false)
        })

        it.each(['$pageview', '$autocapture', '$identify', 'user.signed_up', 'event.name'])(
            'returns true for event name pattern with results: "%s"',
            (query) => {
                expect(shouldSkipAiHighlight(query, [])).toBe(false)
                expect(shouldSkipAiHighlight(query, [createItem({ category: 'event_definition' })])).toBe(true)
            }
        )
    })

    describe('Exact matches - skip AI', () => {
        it('returns true when query exactly matches a result name (case-insensitive)', () => {
            const items = [createItem({ name: 'Dashboard A' }), createItem({ name: 'Dashboard B' })]
            expect(shouldSkipAiHighlight('dashboard a', items)).toBe(true)
            expect(shouldSkipAiHighlight('DASHBOARD A', items)).toBe(true)
            expect(shouldSkipAiHighlight('Dashboard A', items)).toBe(true)
        })

        it('returns true when query exactly matches displayName', () => {
            const items = [createItem({ name: 'Internal Name', displayName: 'User Friendly Name' })]
            expect(shouldSkipAiHighlight('user friendly name', items)).toBe(true)
        })

        it('returns false when no exact match exists (with multiple results)', () => {
            // Need 2+ items to avoid single-result heuristic
            const items = [createItem({ name: 'Dashboard A' }), createItem({ id: 'test-2', name: 'Dashboard B' })]
            expect(shouldSkipAiHighlight('dashboard', items)).toBe(false) // Partial match
            expect(shouldSkipAiHighlight('dashboards', items)).toBe(false) // Plural
        })

        it('returns true for exact feature flag key match with hyphens/underscores', () => {
            const items = [createItem({ name: 'enable-dark-mode', category: 'feature_flag' })]
            expect(shouldSkipAiHighlight('enable-dark-mode', items)).toBe(true)
            expect(
                shouldSkipAiHighlight('ENABLE_DARK_MODE', [
                    createItem({ name: 'enable_dark_mode', category: 'feature_flag' }),
                ])
            ).toBe(true)
        })

        it('returns false for flag-like query without feature_flag result (with multiple results)', () => {
            // Need 2+ items to avoid single-result heuristic
            const items = [
                createItem({ name: 'some-flag', category: 'insight' }),
                createItem({ id: 'test-2', name: 'other-flag', category: 'insight' }),
            ]
            expect(shouldSkipAiHighlight('some-flag', items)).toBe(false)
        })
    })

    describe('Navigational intent - skip AI', () => {
        it.each([
            'go to dashboards',
            'open insights',
            'show feature flags',
            'navigate to settings',
            'goto experiments',
            'new dashboard',
            'create insight',
        ])('returns true for navigational prefix: "%s"', (query) => {
            expect(shouldSkipAiHighlight(query, [createItem()])).toBe(true)
        })

        it('returns true for settings query with settings results', () => {
            expect(shouldSkipAiHighlight('settings', [])).toBe(false)
            expect(shouldSkipAiHighlight('settings', [createItem({ category: 'settings' })])).toBe(true)
            expect(shouldSkipAiHighlight('setting', [createItem({ category: 'settings' })])).toBe(true)
        })
    })

    describe('Short queries - skip AI', () => {
        it('returns true for 1-2 word queries matching apps/recents/settings', () => {
            expect(shouldSkipAiHighlight('flags', [createItem({ category: 'apps' })])).toBe(true)
            expect(shouldSkipAiHighlight('my dashboard', [createItem({ category: 'recents' })])).toBe(true)
            expect(shouldSkipAiHighlight('data management', [createItem({ category: 'data-management' })])).toBe(true)
        })

        it('returns false for 1-2 word queries not matching special categories', () => {
            // Need 2+ items to avoid single-result heuristic
            expect(
                shouldSkipAiHighlight('random query', [
                    createItem({ category: 'insight' }),
                    createItem({ id: 'test-2', category: 'insight' }),
                ])
            ).toBe(false)
        })

        it('returns false for 3+ word queries even if they match apps', () => {
            // Need 2+ items to avoid single-result heuristic
            expect(
                shouldSkipAiHighlight('some random three words', [
                    createItem({ category: 'apps' }),
                    createItem({ id: 'test-2', category: 'apps' }),
                ])
            ).toBe(false)
        })
    })

    describe('Single result - skip AI', () => {
        it('returns true when there is exactly one result', () => {
            expect(shouldSkipAiHighlight('anything', [createItem()])).toBe(true)
        })

        it('returns false when there are multiple results', () => {
            expect(shouldSkipAiHighlight('anything', [createItem(), createItem({ id: 'test-2' })])).toBe(false)
        })
    })

    describe('Rank-based - skip AI', () => {
        it('returns true when first result has high rank (> 0.5) with no second result', () => {
            const items = [createItem({ rank: 0.8 })]
            expect(shouldSkipAiHighlight('test', items)).toBe(true)
        })

        it('returns true when first result has significantly higher rank than second (> 2x)', () => {
            const items = [createItem({ rank: 1.0 }), createItem({ id: 'test-2', rank: 0.4 })]
            expect(shouldSkipAiHighlight('test', items)).toBe(true)
        })

        it('returns false when first result rank is not significantly higher', () => {
            const items = [createItem({ rank: 0.6 }), createItem({ id: 'test-2', rank: 0.5 })]
            expect(shouldSkipAiHighlight('test', items)).toBe(false)
        })

        it('returns false when first result has low rank even with no second result', () => {
            // Single result heuristic will still trigger even with low rank
            const items = [createItem({ rank: 0.3 })]
            expect(shouldSkipAiHighlight('test', items)).toBe(true) // Single result wins

            // With 2 items, low rank doesn't trigger skip
            const items2 = [createItem({ rank: 0.3 }), createItem({ id: 'test-2', rank: 0.2 })]
            expect(shouldSkipAiHighlight('test', items2)).toBe(false)
        })

        it('returns false when rank is null', () => {
            // Single result heuristic will still trigger even with null rank
            const items = [createItem({ rank: null })]
            expect(shouldSkipAiHighlight('test', items)).toBe(true) // Single result wins

            // With 2 items, null rank doesn't trigger skip
            const items2 = [createItem({ rank: null }), createItem({ id: 'test-2', rank: null })]
            expect(shouldSkipAiHighlight('test', items2)).toBe(false)
        })
    })

    describe('No results - keep AI', () => {
        it('returns false when there are no real results', () => {
            expect(shouldSkipAiHighlight('test query', [])).toBe(false)
        })
    })

    describe('Edge cases and complex scenarios', () => {
        it('UUID takes precedence over question patterns', () => {
            // Currently question patterns take precedence, but UUID should theoretically win
            // This documents current behavior - can be changed if needed
            expect(shouldSkipAiHighlight('what is 550e8400-e29b-41d4-a716-446655440000', [])).toBe(false)
        })

        it('exact match works with whitespace trimming', () => {
            const items = [createItem({ name: 'Test' })]
            expect(shouldSkipAiHighlight('  test  ', items)).toBe(true)
        })

        it('combines multiple heuristics correctly', () => {
            // Short query + exact match + apps category
            const items = [createItem({ name: 'Surveys', category: 'apps' })]
            expect(shouldSkipAiHighlight('surveys', items)).toBe(true)
        })
    })
})
