import { renderEmailPreview, renderEmailPreviewFields, unresolvedVariables } from './emailPreview'

describe('emailPreview', () => {
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
            [
                'keeps an unknown root visible',
                'Your plan: {{ customer.plan_name }}',
                'Your plan: {{ customer.plan_name }}',
            ],
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
    })

    describe('renderEmailPreviewFields', () => {
        const person = {
            id: 'person-1',
            properties: { email: 'sam@example.com', first_name: 'Sam' },
        }

        it.each([
            ['a native email, which holds the recipient as an object', { email: '{{ person.properties.email }}' }],
            ['a legacy email input, which holds it as a string', '{{ person.properties.email }}'],
        ])('resolves the recipient of %s', (_name, to) => {
            expect(renderEmailPreviewFields({ to }, person).to).toBe('sam@example.com')
        })

        it('resolves the subject and preheader against the same person', () => {
            expect(
                renderEmailPreviewFields(
                    { subject: 'Hi {{ person.properties.first_name }}', preheader: '{{ person.properties.plan }}' },
                    person
                )
            ).toMatchObject({ subject: 'Hi Sam', preheader: '{{ person.properties.plan }}' })
        })
    })

    describe('unresolvedVariables', () => {
        it.each([
            ['lists every tag a render left behind', 'Hi {{ a }}, your {{ b }} renews', ['a', 'b']],
            ['lists nothing for a fully resolved render', 'Hi Sam, your pro plan renews', []],
            ['reads a tag that spans lines', 'Hi {{\n a \n}}', ['a']],
        ])('%s', (_name, rendered, expected) => {
            expect(unresolvedVariables(rendered)).toEqual(expected)
        })
    })
})
