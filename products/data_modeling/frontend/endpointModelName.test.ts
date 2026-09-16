import { nodeEndpointModel, parseEndpointModelName } from './endpointModelName'

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

describe('nodeEndpointModel', () => {
    it('prefers the stamped link over the name', () => {
        expect(
            nodeEndpointModel({ type: 'endpoint', name: 'renamed_v9', endpoint: { name: 'signups', version: 2 } })
        ).toEqual({ endpointName: 'signups', version: 2 })
    })

    it('falls back to the name for nodes enabled before the link was stamped', () => {
        expect(nodeEndpointModel({ type: 'endpoint', name: 'signups_v2', endpoint: null })).toEqual({
            endpointName: 'signups',
            version: 2,
        })
    })

    it('ignores non-endpoint nodes whatever their name', () => {
        expect(nodeEndpointModel({ type: 'matview', name: 'signups_v2', endpoint: null })).toBeNull()
    })
})
