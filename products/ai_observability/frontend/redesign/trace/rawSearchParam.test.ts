import { combineUrl } from 'kea-router'

import { withRawParams } from './rawSearchParam'

describe('rawSearchParam', () => {
    it.each([
        ['trace_search', '1.50'],
        ['error_search', '{"code": 429}'],
        ['tool_search', 'true'],
        ['person_search', '[1, 2]'],
        ['error', '{"code": 429}'],
        ['tool', '["search", "fetch"]'],
        ['failed_tool', '{"name": "fetch"}'],
    ])('keeps the typed text param %s as typed: %s', (name, typed) => {
        const search = `?${name}=${encodeURIComponent(typed)}`

        expect(withRawParams(combineUrl(`/list${search}`).searchParams, search)[name]).toEqual(typed)
    })

    it('keeps a JSON param that is not a search parsed', () => {
        const search = `?filters=${encodeURIComponent('[{"key": "a"}]')}`

        expect(withRawParams(combineUrl(`/list${search}`).searchParams, search).filters).toEqual([{ key: 'a' }])
    })
})
