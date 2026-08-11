import {
    CyclotronJobTemplateOption,
    insertTemplateReference,
    templateReferenceForOption,
} from './cyclotronJobTemplateSuggestionsLogic'

const optionFor = (example: string): CyclotronJobTemplateOption => ({
    key: 'example',
    description: 'An example',
    example,
})

describe('cyclotron job template suggestions', () => {
    describe('templateReferenceForOption', () => {
        it.each([
            ['a hog expression is wrapped in braces', 'hog', `$1 ?? 'Default value'`, `{$1 ?? 'Default value'}`],
            ['a hog function call is wrapped in braces', 'hog', 'concat($1, $2)', '{concat($1, $2)}'],
            [
                'a liquid output tag keeps its own braces',
                'liquid',
                '{{ person.properties.email }}',
                '{{ person.properties.email }}',
            ],
            [
                'a liquid block tag keeps its own braces',
                'liquid',
                '{% if condition %} Yes {% else %} No {% endif %}',
                '{% if condition %} Yes {% else %} No {% endif %}',
            ],
            [
                'a bare liquid expression is wrapped in output braces',
                'liquid',
                'person.properties.email',
                '{{ person.properties.email }}',
            ],
        ] as [string, 'hog' | 'liquid', string, string][])('%s', (_name, templating, example, expected) => {
            expect(templateReferenceForOption(optionFor(example), templating)).toBe(expected)
        })
    })

    describe('insertTemplateReference', () => {
        it.each([
            ['at a cursor in the middle of the text', 'Hi , welcome', 3, 'Hi {person.name}, welcome'],
            ['at a cursor at the start of the text', 'Hi there', 0, '{person.name}Hi there'],
            ['at a cursor at the end of the text', 'Hi there', 8, 'Hi there{person.name}'],
            ['into empty text', '', 0, '{person.name}'],
        ] as [string, string, number, string][])('inserts %s', (_name, value, cursorOffset, expected) => {
            expect(insertTemplateReference(value, '{person.name}', cursorOffset)).toBe(expected)
        })

        it.each([
            ['the cursor position is unknown', null],
            ['the tracked cursor is past the end of the current text', 99],
        ] as [string, number | null][])('appends when %s', (_name, cursorOffset) => {
            expect(insertTemplateReference('Hi there', '{person.name}', cursorOffset)).toBe('Hi there{person.name}')
        })
    })
})
