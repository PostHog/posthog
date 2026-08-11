import { reconstructionTarget } from './EventFlagsTab'

describe('reconstructionTarget', () => {
    const lookupKeys = { $feature_flag_id: 629210, $feature_flag_version: 5 }

    it.each([
        ['boolean flag looks up the "true" payload', true, 'true'],
        ['multivariate flag looks up its variant payload', 'control', 'control'],
    ])('%s', (_name, response, expectedKey) => {
        expect(reconstructionTarget({ ...lookupKeys, $feature_flag_response: response })).toEqual({
            flagId: 629210,
            version: 5,
            payloadKey: expectedKey,
        })
    })

    it.each([
        ['flag id missing', { $feature_flag_version: 5, $feature_flag_response: true }],
        ['version missing', { $feature_flag_id: 629210, $feature_flag_response: true }],
        ['flag evaluated to false', { ...lookupKeys, $feature_flag_response: false }],
        ['response missing', lookupKeys],
        [
            'SDK already sent the payload',
            { ...lookupKeys, $feature_flag_response: true, $feature_flag_payload: '"1.0.0"' },
        ],
    ])('returns null when %s', (_name, properties) => {
        expect(reconstructionTarget(properties)).toBeNull()
    })
})
