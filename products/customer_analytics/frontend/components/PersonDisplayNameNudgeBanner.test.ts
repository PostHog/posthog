import { ActorsQueryResponse } from '~/queries/schema/schema-general'

import { getPersonsFromResponse } from './PersonDisplayNameNudgeBanner'

describe('getPersonsFromResponse', () => {
    it('should not return null values', () => {
        const response = {
            results: [
                [{ display_name: 'John Doe' }],
                [{ display_name: 'Jane Doe' }],
                [null],
                [{ name: 'Wrong name field' }],
                [['This should be an object']],
            ],
        } as ActorsQueryResponse

        const persons = getPersonsFromResponse(response)
        expect(persons).toEqual([{ display_name: 'John Doe' }, { display_name: 'Jane Doe' }])
    })
})
