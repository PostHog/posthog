import { HogFunctionInvocationGlobalsWithInputs } from '../types'
import { LiquidRenderer } from './liquid'

describe('LiquidRenderer', () => {
    let globals: HogFunctionInvocationGlobalsWithInputs

    beforeEach(() => {
        const fixedTime = new Date('2025-06-01T00:00:00Z')
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())

        globals = {
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
                properties: {
                    email: 'test_person@example.com',
                },
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
    })

    describe('basic rendering', () => {
        it('renders simple variables', () => {
            const template = 'Hello {{ person.name }}!'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(LiquidRenderer['_liquid']).toBeDefined()
            expect(result).toMatchInlineSnapshot(`"Hello test_person!"`)
        })
    })

    describe('memoized initialisation', () => {
        it('only initialises once', () => {
            LiquidRenderer['_liquid'] = null
            LiquidRenderer.renderWithHogFunctionGlobals('Hello {{ person.name }}!', globals)
            expect(LiquidRenderer['_liquid']).toBeDefined()
        })
    })

    describe('custom filters', () => {
        it('handles default filter', () => {
            const template = '{{ value | default: "fallback" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, { ...globals })
            expect(result).toMatchInlineSnapshot(`"fallback"`)
        })

        it('handles date filter with %Y%m%d format', () => {
            const template = '{{ "2024-03-20" | date: "%Y%m%d" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"20240320"`)
        })

        it('handles date filter with %B %-d, %Y at %l:%M %p format', () => {
            const template = '{{ "2024-03-20T15:30:00" | date: "%B %-d, %Y at %l:%M %p" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"March 20, 2024 at  3:30 PM"`)
        })

        it('handles date filter with %l:%M %p format', () => {
            const template = '{{ "2024-03-20T15:30:00" | date: "%l:%M %p" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`" 3:30 PM"`)
        })

        it('handles "now" in date filter', () => {
            const template = '{{ "now" | date: "%Y%m%d" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatch(/^\d{8}$/)
        })
    })

    describe('HTML decoding', () => {
        it('decodes HTML entities', () => {
            const template = '{{ "&lt;div&gt;Hello &amp; World&lt;/div&gt;" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"&lt;div&gt;Hello &amp; World&lt;/div&gt;"`)
        })

        it('renders liquid elements that have been encoded', () => {
            const template = '{% if 1 &lt; 2 %}hello!{% endif %}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"hello!"`)
        })

        it('preserves $ in template', () => {
            const template = '{{ "$100" }}'
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"$100"`)
        })

        it("decodes unlayer's encoded complex example 1", () => {
            const html = `
<div style="font-size: 14px; line-height: 140%; text-align: left; word-wrap: break-word;">
    <p style="line-height: 140%;">hey {{person.properties.email}}</p>
<p style="line-height: 140%;">{% assign event_date_raw = "2025-06-15 14:30:00" %}<br />{% assign event_date = event_date_raw | date: "%Y%m%d" %}</p>
<p style="line-height: 140%;">{% assign today = "now" | date: "%Y%m%d" %}</p>
<p style="line-height: 140%;">{% assign event_friendly = event_date_raw | date: "%B %-d, %Y at %l:%M %p" %}<br />{% if event_date &gt; today %}<br />The event is coming up on {{ event_friendly }}.<br />{% elsif event_date == today %}<br />The event is happening today at {{ event_friendly | date: "%l:%M %p" }}!<br />{% else %}<br />This event took place on {{ event_friendly }}.<br />{% endif %}</p>
  </div>`

            const result = LiquidRenderer.renderWithHogFunctionGlobals(html, globals)
            expect(result).toMatchInlineSnapshot(`
                "
                <div style="font-size: 14px; line-height: 140%; text-align: left; word-wrap: break-word;">
                    <p style="line-height: 140%;">hey test_person@example.com</p>
                <p style="line-height: 140%;"><br /></p>
                <p style="line-height: 140%;"></p>
                <p style="line-height: 140%;"><br /><br />The event is coming up on June 15, 2025 at  2:30 PM.<br /></p>
                  </div>"
            `)
        })

        it("decodes unlayer's encoded complex example 2", () => {
            const html = `
{% assign events_raw = "Launch Party|2025-06-15 18:00:00,Team Retreat|2025-05-28 09:00:00,Product Demo|2025-06-02 14:00:00" %}

{% assign events = events_raw | split: "," %}

{% assign today = "now" | date: "%Y%m%d" %}

<ul>
  
  {% for event in events %}
    {% assign parts       = event | split: "|" %}
    {% assign event_name  = parts[0] %}
    {% assign raw_date    = parts[1] %}
    {% assign event_ymd   = raw_date | date: "%Y%m%d" %}
    {% assign friendly_dt = raw_date | date: "%B %-d, %Y at %l:%M %p" %}
    <li>
      <strong>{{ event_name }}</strong> – 
      {% if event_ymd > today %}
        Scheduled on {{ friendly_dt }}
      {% elsif event_ymd == today %}
        Happening today at {{ raw_date | date: "%l:%M %p" }}
      {% else %}
        Occurred on {{ friendly_dt }}
      {% endif %}
    </li>
  {% endfor %}
</ul>`

            const result = LiquidRenderer.renderWithHogFunctionGlobals(html, globals)
            expect(result).toMatchInlineSnapshot(`
                "






                <ul>
                  
                  
                    
                    
                    
                    
                    
                    <li>
                      <strong>Launch Party</strong> – 
                      
                        Scheduled on June 15, 2025 at  6:00 PM
                      
                    </li>
                  
                    
                    
                    
                    
                    
                    <li>
                      <strong>Team Retreat</strong> – 
                      
                        Occurred on May 28, 2025 at  9:00 AM
                      
                    </li>
                  
                    
                    
                    
                    
                    
                    <li>
                      <strong>Product Demo</strong> – 
                      
                        Scheduled on June 2, 2025 at  2:00 PM
                      
                    </li>
                  
                </ul>"
            `)
        })
    })

    describe('renderWithHogFunctionGlobals', () => {
        it('renders with hog function globals', () => {
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
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatchInlineSnapshot(`"Event: test_event, Person: test_person"`)
        })

        it('includes now in context', () => {
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
            const result = LiquidRenderer.renderWithHogFunctionGlobals(template, globals)
            expect(result).toMatch(/^\d{8}$/)
        })
    })
})
