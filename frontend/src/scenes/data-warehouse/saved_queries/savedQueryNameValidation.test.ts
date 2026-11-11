import { validateSavedQueryName } from './savedQueryNameValidation'

describe('saved query namespace validation', () => {
    test('rejects the namespace container as a model name', () => {
        expect(validateSavedQueryName('models')).toBe(
            'The models namespace needs a model name, for example models.revenue.'
        )
    })

    test.each(['models.revenue', 'models.marts.revenue', 'revenue', 'models_v2'])('accepts %s', (name) => {
        expect(validateSavedQueryName(name)).toBeUndefined()
    })
})
