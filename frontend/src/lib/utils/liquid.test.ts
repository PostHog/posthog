import { LiquidRenderer } from './liquid'

describe('LiquidRenderer', () => {
    const context = { person: { properties: { first_name: 'Ada', company: null } } }

    // Unlayer stores `>` as `&gt;`, so a renderer that skips the decode step compares the
    // literal entity and silently takes the wrong branch.
    it.each([
        ['on one line', '{% if person.properties.first_name != &quot;&quot; %}'],
        ['across lines', '{% if person.properties.first_name\n  != &quot;&quot; %}'],
    ])('renders a tag the editor has escaped %s', (_, openTag) => {
        const template = `${openTag}Hi {{ person.properties.first_name }}{% endif %}`
        expect(LiquidRenderer.render(template, context)).toBe('Hi Ada')
    })

    it.each([
        ['person.properties.first_name', true],
        ['person.properties.company', false],
        ['person.properties.missing', false],
        ['person.properties.first_name | upcase', true],
    ])('resolves(%s) is %s', (expression, expected) => {
        expect(LiquidRenderer.resolves(expression, context)).toBe(expected)
    })

    it('formats money with the currency filter, like the worker does at send time', () => {
        expect(LiquidRenderer.render('{{ amount | currency: "USD" }}', { amount: 1234.5 })).toBe('$1,234.50')
    })

    it.each(['{% unsubscribe_url %}', '{%- unsubscribe_url -%}'])(
        'renders the Customer.io tag %s like the unsubscribe_url variable',
        (tag) => {
            const unsubscribe = { unsubscribe_url: 'https://example.com/preferences?token=abc&team=1' }
            expect(LiquidRenderer.render(`<a href="${tag}">x</a>`, unsubscribe)).toBe(
                LiquidRenderer.render('<a href="{{ unsubscribe_url }}">x</a>', unsubscribe)
            )
        }
    )

    it('treats an unparseable expression as unresolved rather than throwing', () => {
        expect(LiquidRenderer.resolves('person.properties[', context)).toBe(false)
    })
})
