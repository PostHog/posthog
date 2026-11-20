import {
    countUnresolved,
    personPropertiesUsed,
    renderEmailPreview,
    renderEmailPreviewMarked,
    withUnresolvedChips,
} from './emailPreview'

describe('renderEmailPreview', () => {
    const person = {
        id: 'person-1',
        properties: { email: 'sam@example.com', first_name: 'Sam', seats: ['a', 'b'] },
    }

    it.each([
        ['substitutes a property the person has', 'Hi {{ person.properties.first_name }}', 'Hi Sam'],
        [
            'keeps a property the person lacks visible instead of blanking it',
            'Hi {{ person.properties.nickname }}',
            'Hi {{ person.properties.nickname }}',
        ],
        ['keeps an unknown root visible', 'Your plan: {{ customer.plan_name }}', 'Your plan: {{ customer.plan_name }}'],
        [
            'leaves a filter to supply its own fallback',
            "Hi {{ person.properties.nickname | default: 'there' }}",
            'Hi there',
        ],
        [
            'keeps a missing property visible when its tag spans lines',
            'Hi {{\n person.properties.nickname \n}}',
            'Hi {{\n person.properties.nickname \n}}',
        ],
        [
            'keeps a missing property visible inside a block',
            "{% if person.properties.email contains 'example' %}Hi {{ person.properties.nickname }}{% endif %}",
            'Hi {{ person.properties.nickname }}',
        ],
        ['renders a loop item', '{% for seat in person.properties.seats %}{{ seat }}{% endfor %}', 'ab'],
        ['renders a name the template assigns', '{% assign n = person.properties.first_name %}Hi {{ n }}', 'Hi Sam'],
        [
            'leaves a tag the template already marked raw alone',
            'Hi {% raw %}{{ person.properties.nickname }}{% endraw %}',
            'Hi {{ person.properties.nickname }}',
        ],
        [
            'reads a filter argument containing the closing braces as part of the expression',
            'Hi {{ person.properties.nickname | default: "}}" }}',
            'Hi }}',
        ],
    ])('%s', (_name, template, expected) => {
        expect(renderEmailPreview(template, person)).toBe(expected)
    })

    it('decodes liquid tags the email editor escaped', () => {
        // Unlayer escapes the whole document, so a comparison arrives as &gt; and must still evaluate.
        expect(
            renderEmailPreview('{% if person.properties.age &gt; 20 %}adult{% endif %}', {
                id: 'person-2',
                properties: { age: 30 },
            })
        ).toBe('adult')
    })

    it('returns the template untouched when there is no person to render against', () => {
        expect(renderEmailPreview('Hi {{ person.properties.first_name }}', null)).toBe(
            'Hi {{ person.properties.first_name }}'
        )
    })

    it('falls back to the template when the output would be huge', () => {
        const template = `{% for i in (1..1100) %}${'x'.repeat(10000)}{% endfor %}`

        expect(renderEmailPreview(template, person)).toBe(template)
    })

    it('gives up on a runaway loop instead of freezing the page', () => {
        const template = '{% for i in (1..100000000) %}x{% endfor %}'

        expect(renderEmailPreview(template, person)).toBe(template)
    })

    it('finds person properties the editor wrote in bracket notation', () => {
        expect(personPropertiesUsed(['{{ person.properties.plan }} {{ person.properties["renews on"] }}'])).toEqual([
            'plan',
            'renews on',
        ])
    })

    it.each([
        ['an unclosed tag', "{{ 'a<' | strip_html }} {{ '<b>bold</b>' | strip_html }}", 'a&lt; bold'],
        ['a list, joined as Liquid joins it', '{{ person.properties.seats | strip_html }}', 'ab'],
        ['text whose lowercase form is longer', "{{ 'İ<style>x</style>tail' | strip_html }}", 'İtail'],
        [
            'a script, style or comment block',
            "{{ '<script>x</script><style>.a{}</style>b<!-- c > d -->e' | strip_html }}",
            'be',
        ],
    ])('strips html from %s without hanging', (_name, template, expected) => {
        expect(renderEmailPreview(template, person)).toBe(expected)
    })

    it('falls back to the template rather than throwing on a broken tag', () => {
        expect(renderEmailPreview('{% for %}', person)).toBe('{% for %}')
    })

    it('shows a missing value as a chip in the text and as its label inside an attribute', () => {
        const html = withUnresolvedChips(
            renderEmailPreviewMarked(
                '<p>Hi {{ person.properties.first_name }}, <a href="/{{ person.properties.plan_name }}">plan</a></p>',
                { id: 'person-3', properties: {} }
            )
        )
        const doc = new DOMParser().parseFromString(html, 'text/html')

        expect(doc.querySelector('p > span')?.textContent).toBe('first name')
        expect(doc.querySelector('a')?.getAttribute('href')).toBe('/plan name')
    })

    it('counts quickly when a person value is full of chip fences', () => {
        const rendered = renderEmailPreviewMarked('{{ person.properties.bio }}', {
            id: 'person-5',
            properties: { bio: '\uE000'.repeat(80000) },
        })
        const started = performance.now()

        expect(countUnresolved(rendered)).toBe(0)
        expect(performance.now() - started).toBeLessThan(1000)
    })

    it('counts a missing value once however often the email uses it', () => {
        const rendered = renderEmailPreviewMarked(
            '{{ person.properties.plan }} {{ person.properties.plan }} {{ person.properties.seats }}',
            { id: 'person-4', properties: {} }
        )

        expect(countUnresolved(rendered)).toBe(2)
    })
})
