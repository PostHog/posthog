import { LiquidRenderer } from './liquid'

describe('LiquidRenderer', () => {
    const context = { person: { properties: { first_name: 'Ada', company: null } } }

    it('renders a template the editor has escaped', () => {
        // Unlayer stores `>` as `&gt;`, so a renderer that skips the decode step compares the
        // literal entity and silently takes the wrong branch.
        const template =
            '{% if person.properties.first_name != &quot;&quot; %}Hi {{ person.properties.first_name }}{% endif %}'
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

    it('treats an unparseable expression as unresolved rather than throwing', () => {
        expect(LiquidRenderer.resolves('person.properties[', context)).toBe(false)
    })
})
