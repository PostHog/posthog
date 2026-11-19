import { countUnresolved, renderEmailPreview, renderEmailPreviewMarked, withUnresolvedChips } from './emailPreview'

describe('renderEmailPreview', () => {
    const person = {
        id: 'person-1',
        properties: { email: 'sam@example.com', first_name: 'Sam' },
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

    it('counts a missing value once however often the email uses it', () => {
        const rendered = renderEmailPreviewMarked(
            '{{ person.properties.plan }} {{ person.properties.plan }} {{ person.properties.seats }}',
            { id: 'person-4', properties: {} }
        )

        expect(countUnresolved(rendered)).toBe(2)
    })
})
