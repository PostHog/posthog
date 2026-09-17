import { getCustomerJourneyEligibility } from './customerJourneyEligibility'

const payload = {
    schema_version: 1,
    registry_version: 'test-v1',
    organizations: [{ region: 'US', organization_id: 'synthetic-organization' }],
}
const context = { region: 'US', organization_id: 'synthetic-organization', project_id: 101 }

describe('customer journey eligibility', () => {
    it.each([
        ['selected organization', true, payload, context, true],
        ['another project in selected organization', true, payload, { ...context, project_id: 202 }, true],
        ['flag off', false, payload, context, false],
        ['nonboolean flag', 'test', payload, context, false],
        [
            'stale flag after organization switch',
            true,
            payload,
            { ...context, organization_id: 'another-organization' },
            false,
        ],
        ['region mismatch', true, payload, { ...context, region: 'EU' }, false],
        ['unknown region', true, payload, { ...context, region: null }, false],
        ['missing project', true, payload, { ...context, project_id: null }, false],
        ['absent payload', true, undefined, context, false],
        ['unsupported schema', true, { ...payload, schema_version: 2 }, context, false],
        ['missing registry version', true, { ...payload, registry_version: '' }, context, false],
        ['malformed organizations', true, { ...payload, organizations: {} }, context, false],
        [
            'partially malformed list',
            true,
            { ...payload, organizations: [...payload.organizations, {}] },
            context,
            false,
        ],
    ])('%s', (_, enabled, candidate, current, eligible) => {
        expect(getCustomerJourneyEligibility(enabled, candidate, current)).toEqual(
            eligible ? { ...current, registry_version: 'test-v1' } : null
        )
    })
})
