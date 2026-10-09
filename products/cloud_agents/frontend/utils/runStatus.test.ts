import { getRunStatusDisplay } from './runStatus'

describe('getRunStatusDisplay', () => {
    test.each([
        ['queued', null, null, 'Queued', undefined],
        ['running', null, null, 'Running', undefined],
        ['idle', 'turn_closed', null, 'Waiting for you', 'The agent finished its turn. Send a message to continue.'],
        ['idle', 'turn_closed', 'Custom detail', 'Waiting for you', 'Custom detail'],
        ['idle', 'timed_out', 'The run stopped.', 'Timed out', 'The run stopped.'],
        ['idle', 'provision_failed', null, 'Could not start', undefined],
        ['idle', 'unexpected_failure', null, 'Failed', undefined],
        ['idle', 'credit_spent', null, 'Usage limit reached', undefined],
        ['done', 'finished', null, 'Merged', undefined],
        ['done', 'closed', null, 'Closed', undefined],
        ['done', 'cancelled', null, 'Canceled', undefined],
        ['done', null, null, 'Done', undefined],
    ] as const)('status %s with reason %s and detail %s shows %s', (status, reason, detail, label, tooltip) => {
        const display = getRunStatusDisplay(status, reason, detail)
        expect(display.label).toEqual(label)
        expect(display.tooltip).toEqual(tooltip)
    })
})
