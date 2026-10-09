import { IntegrationType } from '~/types'

import { authorizedIntegrationId } from './IntegrationChoice'

const integration = (id: number, kind: string): IntegrationType => ({ id, kind }) as IntegrationType

describe('SourceIntegrationChoice', () => {
    // Reconnecting mid-setup leaves the field pointing at the replaced connection, which blocks the
    // wizard on the account step with no way forward but starting over.
    it.each([
        ['adopts the connection the callback just created', { integration_id: '7' }, 7],
        ['ignores a connection belonging to another provider', { integration_id: '8' }, null],
        ['ignores an id no connection matches', { integration_id: '99' }, null],
        ['ignores a blank param', { integration_id: '' }, null],
        ['ignores a missing param', {}, null],
    ])('%s', (_name, searchParams, expected) => {
        const integrations = [integration(7, 'linkedin-ads'), integration(8, 'google-ads')]
        expect(authorizedIntegrationId(searchParams, integrations, 'linkedin-ads')).toEqual(expected)
    })

    it('waits for the connection list rather than adopting an unverified id', () => {
        expect(authorizedIntegrationId({ integration_id: '7' }, null, 'linkedin-ads')).toBeNull()
    })
})
