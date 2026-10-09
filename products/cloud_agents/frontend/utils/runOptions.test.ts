import {
    parseOutputSchema,
    repositoryFields,
    toRepositories,
    validateIdleMinutes,
    validateRepository,
} from './runOptions'

describe('runOptions', () => {
    test.each([
        ['', '', null],
        ['  ', 'main', null],
        ['acme/web', '', [{ name: 'acme/web', initial_branch: null }]],
        [' acme/web ', ' release ', [{ name: 'acme/web', initial_branch: 'release' }]],
    ])('repository %p and branch %p make the list %p', (repository, branch, expected) => {
        expect(toRepositories(repository, branch)).toEqual(expected)
    })

    test.each([
        [null, { repository: '', branch: '' }],
        [[], { repository: '', branch: '' }],
        [[{ name: 'acme/web' }], { repository: 'acme/web', branch: '' }],
        [[{ name: 'acme/web', initial_branch: 'main' }], { repository: 'acme/web', branch: 'main' }],
    ])('the repositories %p fill the fields %p', (repositories, expected) => {
        expect(repositoryFields(repositories)).toEqual(expected)
    })

    test.each([
        ['', undefined],
        ['acme/web', undefined],
        ['acme', 'Use the form owner/name, for example acme/web'],
        ['https://github.com/acme/web', 'Use the form owner/name, for example acme/web'],
    ])('the repository %p gives the error %p', (repository, expected) => {
        expect(validateRepository(repository)).toEqual(expected)
    })

    test.each([
        [null, undefined],
        [1, undefined],
        [120, undefined],
        [0, expect.stringContaining('from 1 to 120')],
        [121, expect.stringContaining('from 1 to 120')],
        [2.5, expect.stringContaining('from 1 to 120')],
    ])('the idle time %p gives the error %p', (minutes, expected) => {
        expect(validateIdleMinutes(minutes)).toEqual(expected)
    })

    test.each([
        ['', { schema: null }],
        ['  ', { schema: null }],
        ['{"type": "object"}', { schema: { type: 'object' } }],
        ['{"type": ', { schema: null, error: 'Enter valid JSON' }],
        ['[]', { schema: null, error: expect.stringContaining('JSON object') }],
        ['"text"', { schema: null, error: expect.stringContaining('JSON object') }],
        ['null', { schema: null, error: expect.stringContaining('JSON object') }],
    ])('the schema text %p reads as %p', (text, expected) => {
        expect(parseOutputSchema(text)).toEqual(expected)
    })
})
