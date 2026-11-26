import { ChecksHealth, healthyMessage } from './healthyMessage'

describe('healthyMessage', () => {
    it.each<[ChecksHealth, string]>([
        ['all-passed', 'No models failed to refresh, are suspended, or are behind schedule. All checks passed.'],
        [
            'some-not-passed',
            "No models failed to refresh, are suspended, or are behind schedule. No checks are failing. Some haven't passed yet.",
        ],
        ['none', 'No models failed to refresh, are suspended, or are behind schedule.'],
    ])('with checks %s says only what was checked', (checksHealth, expected) => {
        expect(healthyMessage(checksHealth)).toEqual(expected)
    })
})
