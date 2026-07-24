import { buildWizardSteps } from './buildWizardSteps'

describe('buildWizardSteps', () => {
    const baseInput = {
        nameNode: null,
        definitionNode: null,
        previewNode: null,
        scheduleNode: null,
        notifyNode: null,
        advancedNode: null,
        summary: { fires: '', cadence: '', notifies: '' },
        alertFormHasErrors: false,
        alertName: 'My alert',
    }

    it.each([
        ['missing name', { alertName: '' }, 'monitor', 'Enter an alert name.'],
        ['invalid threshold', { thresholdBoundsFormError: 'Enter a threshold' }, 'monitor', 'Enter a threshold'],
        [
            'invalid schedule',
            { alertFormHasErrors: true, scheduleRestrictionFormError: 'Choose an end time' },
            'schedule',
            'Choose an end time',
        ],
    ])('blocks the step containing %s errors', (_name, overrides, stepKey, expectedReason) => {
        const steps = buildWizardSteps({ ...baseInput, ...overrides })
        const step = steps.find((step) => step.key === stepKey)

        expect(step).toMatchObject({ canAdvance: false, cannotAdvanceReason: expectedReason })
    })
})
