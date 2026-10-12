import { validateFolderName, validateSavedQueryName } from './savedQueryNameValidation'

describe('saved query namespace validation', () => {
    test('rejects the namespace container as a model name', () => {
        expect(validateSavedQueryName('models')).toBe(
            'The models namespace needs a model name, for example models.revenue.'
        )
    })

    test.each(['models.revenue', 'models.marts.revenue', 'revenue', 'models_v2'])('accepts %s', (name) => {
        expect(validateSavedQueryName(name)).toBeUndefined()
    })

    test.each([
        ['Marts', 'A folder with this name already exists'],
        ['  Marts  ', 'A folder with this name already exists'],
        ['   ', 'You must enter a folder name'],
        ['marts', undefined],
        ['Staging', undefined],
    ])('folder name %j gives %j', (name, expected) => {
        expect(validateFolderName(name, [{ name: 'Marts' }])).toBe(expected)
    })
})
