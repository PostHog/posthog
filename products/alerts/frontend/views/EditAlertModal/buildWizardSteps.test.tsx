import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { AlertWizard } from 'products/alerts/frontend/components/AlertWizard'

import { buildWizardSteps } from './buildWizardSteps'

describe('buildWizardSteps', () => {
    afterEach(cleanup)

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
        ['invalid threshold', { thresholdValidationError: 'Enter a threshold' }, 'monitor', 'Enter a threshold'],
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

    it('keeps the user on Monitor when its threshold is invalid', () => {
        const onSubmitAttempted = jest.fn()
        const steps = buildWizardSteps({
            ...baseInput,
            thresholdValidationError: 'Enter at least one threshold (less than or more than)',
        })
        render(
            <AlertWizard
                title="New alert"
                steps={steps}
                isSubmitting={false}
                hasChanges
                onBack={jest.fn()}
                onSubmitAttempted={onSubmitAttempted}
            />
        )

        const scheduleStep = screen.getByText('Schedule').closest('button')
        expect((scheduleStep as HTMLButtonElement).disabled).toBe(true)
        fireEvent.click(scheduleStep as HTMLButtonElement)
        expect(screen.getByText('Pick what this alert watches and when it should fire.')).toBeTruthy()

        fireEvent.click(screen.getByText('Continue'))
        expect(onSubmitAttempted).toHaveBeenCalledTimes(1)
        expect(screen.getByText('Enter at least one threshold (less than or more than)')).toBeTruthy()
        expect(screen.getByText('Pick what this alert watches and when it should fire.')).toBeTruthy()
    })

    it('does not advance when Enter is used inside a nested picker', () => {
        const steps = buildWizardSteps({
            ...baseInput,
            notifyNode: (
                <div data-prevent-wizard-submit>
                    <input aria-label="Notification recipient" />
                </div>
            ),
        })
        render(
            <AlertWizard
                title="New alert"
                steps={steps}
                isSubmitting={false}
                hasChanges
                onBack={jest.fn()}
                onSubmitAttempted={jest.fn()}
            />
        )
        fireEvent.click(screen.getByText('Notify'))

        const eventWasNotCancelled = fireEvent.keyDown(screen.getByLabelText('Notification recipient'), {
            key: 'Enter',
        })

        expect(eventWasNotCancelled).toBe(false)
        expect(screen.getByText('Who gets told when this alert fires.')).toBeTruthy()
        expect(screen.queryByText('Confirm what this alert will do, then create it.')).toBeNull()
    })
})
