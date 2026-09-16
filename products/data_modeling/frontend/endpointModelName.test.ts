import { parseEndpointModelName } from './endpointModelName'

describe('parseEndpointModelName', () => {
    test.each([
        ['weekly-active-users_v5', { endpointName: 'weekly-active-users', version: 5 }],
        ['usage_v2_daily_v13', { endpointName: 'usage_v2_daily', version: 13 }],
        ['plain_view', null],
        ['trailing_v', null],
        ['_v3', null],
    ])('%s', (name, expected) => {
        expect(parseEndpointModelName(name)).toEqual(expected)
    })
})
