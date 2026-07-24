import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'
import { initKeaTests } from '~/test/init'

import { triggerGroupFormLogic } from './triggerGroupFormLogic'

describe('triggerGroupFormLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const noop = (): void => {}

    it.each<[string, SessionRecordingTriggerGroup | undefined, number | undefined, number]>([
        ['new group inherits the team legacy rate instead of defaulting to 100%', undefined, 0.5, 50],
        ['new group falls back to 100% when the team has no legacy rate', undefined, undefined, 100],
        [
            'existing 0% group stays 0% and is not rewritten to 100%',
            { id: 'zero', name: 'Zero', sampleRate: 0, conditions: { matchType: 'all' } },
            0.5,
            0,
        ],
        [
            'existing group keeps its own rate over the legacy default',
            { id: 'thirty', name: 'Thirty', sampleRate: 0.3, conditions: { matchType: 'all' } },
            0.5,
            30,
        ],
    ])('%s', (_description, group, defaultSampleRate, expected) => {
        const logic = triggerGroupFormLogic({ group, defaultSampleRate, onSave: noop, onCancel: noop })
        logic.mount()

        expect(logic.values.triggerGroup.sampleRate).toBe(expected)
    })
})
