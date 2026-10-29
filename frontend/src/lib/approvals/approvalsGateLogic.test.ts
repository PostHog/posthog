import { experimentUpdatePolicyCoversOperations } from './approvalsGateLogic'

describe('experimentUpdatePolicyCoversOperations', () => {
    test.each([
        ['no conditions', {}, true],
        ['any change to release conditions', { type: 'any_change', field: 'release_conditions' }, true],
        ['a threshold without its operator', { type: 'before_after', field: 'rollout_percentage', value: 50 }, true],
        ['an unknown condition type', { type: 'rollout_widens', field: 'rollout_percentage' }, true],
        ['a condition that is not an object', 'rollout over 50', true],
        ['a rollout threshold', { type: 'before_after', field: 'rollout_percentage', operator: '>', value: 50 }, false],
        ['any change to the rollout', { type: 'any_change', field: 'rollout_percentage' }, false],
    ])('%s', (_name, conditions, expected) => {
        expect(experimentUpdatePolicyCoversOperations(conditions)).toBe(expected)
    })
})
