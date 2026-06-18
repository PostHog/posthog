import { coerceTemplateValueForDisplay } from './CyclotronJobInputs'

describe('coerceTemplateValueForDisplay', () => {
    it.each([
        ['plain string', 'hello', 'hog', 'hello'],
        ['template string', 'Hi {person.properties.name}', 'hog', 'Hi {person.properties.name}'],
        ['empty string', '', 'hog', ''],
        ['null', null, 'hog', ''],
        ['undefined', undefined, 'hog', ''],
        // Single-expression hog templates evaluate to the raw value, preserving the type at runtime
        ['boolean true (hog)', true, 'hog', '{true}'],
        ['boolean false (hog)', false, 'hog', '{false}'],
        ['number (hog)', 42, 'hog', '{42}'],
        ['float (hog)', 0.5, 'hog', '{0.5}'],
        // Liquid renders to strings anyway, so the plain string form is the closest representation
        ['boolean (liquid)', true, 'liquid', 'true'],
        ['number (liquid)', 42, 'liquid', '42'],
        ['boolean (no templating)', true, false, 'true'],
        ['object', { a: 1 }, 'hog', '{"a":1}'],
        ['array', [1, 'two'], 'hog', '[1,"two"]'],
    ] as [string, unknown, 'hog' | 'liquid' | false, string][])('coerces %s', (_name, value, templating, expected) => {
        expect(coerceTemplateValueForDisplay(value, templating)).toBe(expected)
    })
})
