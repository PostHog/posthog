import { ListScope, scopeFromUrl, scopeRequestParams } from './listScopes'

describe('listScopes', () => {
    it('reads the first scope its list accepts from the url', () => {
        expect(scopeFromUrl('?error=a%25b%0Ac&person=p1', ['person', 'error', 'tool'])).toEqual({
            kind: 'person',
            value: 'p1',
        })
        expect(scopeFromUrl('?error=a%25b%0Ac', ['person'])).toBeNull()
        expect(scopeFromUrl('?error=a%25b%0Ac', ['error'])).toEqual({ kind: 'error', value: 'a%b\nc' })
        expect(scopeFromUrl('?tool=', ['tool'])).toBeNull()
    })

    it.each<[ListScope | null, ReturnType<typeof scopeRequestParams>]>([
        [{ kind: 'person', value: 'p1' }, { person_id: 'p1' }],
        [{ kind: 'error', value: 'Rate limit exceeded' }, { error: 'Rate limit exceeded' }],
        [{ kind: 'tool', value: 'search_docs' }, { tool: 'search_docs' }],
        [null, {}],
    ])('sends %j as its api param', (scope, params) => {
        expect(scopeRequestParams(scope)).toEqual(params)
    })
})
