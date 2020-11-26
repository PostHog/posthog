import { identifierToHuman } from './utils'

test('identifier humanizes properly', () => {
    expect(identifierToHuman('testIdentifier')).toBe('Test Identifier')
    expect(identifierToHuman('testIdentifierX')).toBe('Test Identifier X')
    expect(identifierToHuman('something     ')).toBe('Something')
    expect(identifierToHuman('  some_property')).toBe('Some Property')
    expect(identifierToHuman(' Number666')).toBe('Number 666')
    expect(identifierToHuman('7x')).toBe('7x')
    expect(identifierToHuman('7X')).toBe('7 X')
    expect(identifierToHuman('500')).toBe('500')
    expect(identifierToHuman(404)).toBe('404')
    expect(identifierToHuman('CreateProject')).toBe('Create Project')
})
