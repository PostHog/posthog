import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { GuidedWizardStep, GuidedWizardStepper } from './GuidedWizardStepper'

type TestStep = 'intro' | 'first' | 'second' | 'third' | 'done'

const STEPS: GuidedWizardStep<TestStep>[] = [
    { step: 'first', label: 'First' },
    { step: 'second', label: 'Second' },
    { step: 'third', label: 'Third', optional: true },
]

describe('GuidedWizardStepper', () => {
    afterEach(cleanup)

    it('renders all steps, marking completed and current ones', () => {
        render(<GuidedWizardStepper steps={STEPS} currentStep="second" />)

        expect(screen.getByText('First')).toBeInTheDocument()
        expect(screen.getByText('Second')).toBeInTheDocument()
        expect(screen.getByText('Third')).toBeInTheDocument()
        expect(screen.getByText('optional')).toBeInTheDocument()

        // Completed steps show a checkmark instead of their number, upcoming steps keep theirs
        expect(screen.queryByText('1')).not.toBeInTheDocument()
        expect(screen.getByText('3')).toBeInTheDocument()
        expect(screen.getByText('Second').closest('button')).toHaveAttribute('aria-current', 'step')
        expect(screen.getByText('First').closest('button')).not.toHaveAttribute('aria-current')

        // Without an onStepClick handler the steps aren't navigable
        expect(screen.getByText('Third').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('renders each step dataAttr as a data-attr on its button', () => {
        render(
            <GuidedWizardStepper
                steps={STEPS.map((step) => ({ ...step, dataAttr: `wizard-step-${step.step}` }))}
                currentStep="first"
            />
        )

        expect(screen.getByText('Second').closest('button')).toHaveAttribute('data-attr', 'wizard-step-second')
    })

    it.each([
        ['before the steps (e.g. a template picker)', 'intro', 'start', ['1', '2', '3']],
        ['after the steps (e.g. a success screen)', 'done', 'end', []],
    ] as [string, TestStep, 'start' | 'end', string[]][])(
        'sorts an unlisted current step %s',
        (_description, currentStep, unlistedStepPosition, visibleNumbers) => {
            render(
                <GuidedWizardStepper
                    steps={STEPS}
                    currentStep={currentStep}
                    unlistedStepPosition={unlistedStepPosition}
                />
            )

            // A step number is shown while upcoming and replaced by a checkmark once completed
            for (const number of ['1', '2', '3']) {
                if (visibleNumbers.includes(number)) {
                    expect(screen.getByText(number)).toBeInTheDocument()
                } else {
                    expect(screen.queryByText(number)).not.toBeInTheDocument()
                }
            }
        }
    )

    it('calls onStepClick with the clicked step', () => {
        const onStepClick = jest.fn()
        render(<GuidedWizardStepper steps={STEPS} currentStep="second" onStepClick={onStepClick} />)

        fireEvent.click(screen.getByText('Third'))
        expect(onStepClick).toHaveBeenCalledWith('third')
    })

    it('shows the error messages as a tooltip on the errored current step', async () => {
        render(
            <GuidedWizardStepper steps={STEPS} currentStep="second" stepErrors={{ second: ['Something is wrong'] }} />
        )

        const warningIcon = screen.getByText('Second').closest('button')!.querySelector('svg')!
        fireEvent.pointerEnter(warningIcon, { pointerType: 'mouse' })
        fireEvent.mouseEnter(warningIcon)
        // The tooltip's hover-intent detection needs pointer movement, not just enter
        fireEvent.pointerMove(warningIcon, { pointerType: 'mouse' })
        fireEvent.mouseMove(warningIcon)

        expect(await screen.findByText('Something is wrong')).toBeInTheDocument()
    })

    it('ignores clicks on a disabled step and explains why in a tooltip', async () => {
        const onStepClick = jest.fn()
        render(
            <GuidedWizardStepper
                steps={STEPS}
                currentStep="second"
                onStepClick={onStepClick}
                disabledSteps={{ first: 'This step is locked' }}
            />
        )

        const disabledButton = screen.getByText('First').closest('button')!
        expect(disabledButton).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(disabledButton)
        expect(onStepClick).not.toHaveBeenCalled()

        // aria-disabled (not disabled) keeps the button hoverable so the tooltip can explain the lock
        fireEvent.pointerEnter(disabledButton, { pointerType: 'mouse' })
        fireEvent.mouseEnter(disabledButton)
        fireEvent.pointerMove(disabledButton, { pointerType: 'mouse' })
        fireEvent.mouseMove(disabledButton)
        expect(await screen.findByText('This step is locked')).toBeInTheDocument()
    })

    it('blocks forward navigation but allows going back when the current step has errors', () => {
        const onStepClick = jest.fn()
        render(
            <GuidedWizardStepper
                steps={STEPS}
                currentStep="second"
                onStepClick={onStepClick}
                stepErrors={{ second: ['Something is wrong'] }}
            />
        )

        // Blocked steps use aria-disabled, so the click reaches the handler and exercises its guard
        const forwardButton = screen.getByText('Third').closest('button')
        expect(forwardButton).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(forwardButton!)
        expect(onStepClick).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('First'))
        expect(onStepClick).toHaveBeenCalledWith('first')
    })
})
