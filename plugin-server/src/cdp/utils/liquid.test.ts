import { HogFunctionInvocationGlobalsWithInputs } from '../types'
import { LiquidRenderer } from './liquid'

describe('LiquidRenderer', () => {
    let renderer: LiquidRenderer

    beforeEach(() => {
        renderer = new LiquidRenderer()
    })

    describe('basic rendering', () => {
        it('renders simple variables', async () => {
            const template = 'Hello {{ name }}!'
            const context = { name: 'World' }
            const result = await renderer['render'](template, context)
            expect(result).toBe('Hello World!')
        })

        it('renders nested variables', async () => {
            const template = 'Hello {{ user.name }}!'
            const context = { user: { name: 'World' } }
            const result = await renderer['render'](template, context)
            expect(result).toBe('Hello World!')
        })
    })

    describe('custom filters', () => {
        it('handles default filter', async () => {
            const template = '{{ value | default: "fallback" }}'
            const result = await renderer['render'](template, { value: null })
            expect(result).toBe('fallback')
        })

        it('handles date filter with %Y%m%d format', async () => {
            const template = '{{ "2024-03-20" | date: "%Y%m%d" }}'
            const result = await renderer['render'](template, {})
            expect(result).toBe('20240320')
        })

        it('handles date filter with %B %-d, %Y at %l:%M %p format', async () => {
            const template = '{{ "2024-03-20T15:30:00" | date: "%B %-d, %Y at %l:%M %p" }}'
            const result = await renderer['render'](template, {})
            expect(result).toBe('March 20, 2024 at 3:30 PM')
        })

        it('handles date filter with %l:%M %p format', async () => {
            const template = '{{ "2024-03-20T15:30:00" | date: "%l:%M %p" }}'
            const result = await renderer['render'](template, {})
            expect(result).toBe('3:30 PM')
        })

        it('handles "now" in date filter', async () => {
            const template = '{{ "now" | date: "%Y%m%d" }}'
            const result = await renderer['render'](template, {})
            expect(result).toMatch(/^\d{8}$/)
        })
    })

    describe('HTML decoding', () => {
        it('decodes HTML entities', async () => {
            const template = '{{ "&lt;div&gt;Hello &amp; World&lt;/div&gt;" }}'
            const result = await renderer['render'](template, {})
            expect(result).toBe('<div>Hello & World</div>')
        })

        it('preserves $ in template', async () => {
            const template = '{{ "$100" }}'
            const result = await renderer['render'](template, {})
            expect(result).toBe('$100')
        })
    })

    describe('renderWithHogFunctionGlobals', () => {
        it('renders with hog function globals', async () => {
            const template = 'Event: {{ event.event }}, Person: {{ person.name }}'
            const globals: HogFunctionInvocationGlobalsWithInputs = {
                event: {
                    uuid: 'test-uuid',
                    event: 'test_event',
                    distinct_id: 'test-id',
                    properties: {},
                    elements_chain: '',
                    timestamp: '2024-03-20T00:00:00Z',
                    url: 'https://test.com',
                },
                person: {
                    id: 'test-id',
                    properties: {},
                    name: 'test_person',
                    url: 'https://test.com',
                },
                groups: {
                    'test-group': {
                        id: 'test-group-id',
                        type: 'test-group-type',
                        index: 0,
                        url: 'https://test.com',
                        properties: {},
                    },
                },
                project: {
                    id: 1,
                    name: 'test-project',
                    url: 'https://test.com',
                },
                source: {
                    name: 'test-source',
                    url: 'https://test.com',
                },
                inputs: {},
            }
            const result = await renderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toBe('Event: test_event, Person: test_person')
        })

        it('includes now in context', async () => {
            const template = '{{ now | date: "%Y%m%d" }}'
            const globals: HogFunctionInvocationGlobalsWithInputs = {
                event: {
                    uuid: 'test-uuid',
                    event: 'test_event',
                    distinct_id: 'test-id',
                    properties: {},
                    elements_chain: '',
                    timestamp: '2024-03-20T00:00:00Z',
                    url: 'https://test.com',
                },
                person: {
                    id: 'test-id',
                    properties: {},
                    name: 'test_person',
                    url: 'https://test.com',
                },
                groups: {
                    'test-group': {
                        id: 'test-group-id',
                        type: 'test-group-type',
                        index: 0,
                        url: 'https://test.com',
                        properties: {},
                    },
                },
                project: {
                    id: 1,
                    name: 'test-project',
                    url: 'https://test.com',
                },
                source: {
                    name: 'test-source',
                    url: 'https://test.com',
                },
                inputs: {},
            }
            const result = await renderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatch(/^\d{8}$/)
        })
    })
})
