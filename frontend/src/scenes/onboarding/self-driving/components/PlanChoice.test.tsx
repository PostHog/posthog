import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { onboardingLogic } from '../onboardingLogic'
import { PlanChoice } from './PlanChoice'

describe('PlanChoice', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests(false)
        logic = onboardingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    const planSelectedCalls = (capture: jest.SpyInstance): unknown[] =>
        capture.mock.calls.filter(([event]) => event === 'onboarding plan selected')

    it('reports the free pick once and continues', () => {
        const capture = jest.spyOn(posthog, 'capture')
        const onContinue = jest.fn()

        render(
            <PlanChoice
                platformProduct={null}
                inboxProduct={null}
                products={undefined}
                onContinue={onContinue}
                completing={false}
            />
        )
        fireEvent.click(screen.getByText('Start free'))

        expect(planSelectedCalls(capture)).toHaveLength(1)
        expect(onContinue).toHaveBeenCalledTimes(1)
        capture.mockRestore()
    })

    it('shows a pending state on both CTAs while the pick completes', () => {
        const onContinue = jest.fn()

        const { container } = render(
            <PlanChoice
                platformProduct={null}
                inboxProduct={null}
                products={undefined}
                onContinue={onContinue}
                completing={true}
            />
        )

        expect(screen.getByText('Setting things up…')).toBeTruthy()
        expect(screen.queryByText('Start free')).toBeNull()
        const free = container.querySelector('[data-attr="self-driving-onboarding-free"]')
        const subscribe = container.querySelector('[data-attr="self-driving-onboarding-subscribe"]')
        expect(free?.getAttribute('aria-disabled')).toBe('true')
        expect(subscribe?.getAttribute('aria-disabled')).toBe('true')

        fireEvent.click(free!)
        expect(onContinue).not.toHaveBeenCalled()
    })

    it('drops a race click once completion is already in flight', () => {
        // The prop is still false (the button has not re-rendered as pending yet), but the completion
        // has started. Without the live guard this second click would re-fire the funnel event.
        logic.actions.setIsCompleting(true)
        const capture = jest.spyOn(posthog, 'capture')
        const onContinue = jest.fn()

        render(
            <PlanChoice
                platformProduct={null}
                inboxProduct={null}
                products={undefined}
                onContinue={onContinue}
                completing={false}
            />
        )
        fireEvent.click(screen.getByText('Start free'))

        expect(planSelectedCalls(capture)).toHaveLength(0)
        expect(onContinue).not.toHaveBeenCalled()
        capture.mockRestore()
    })
})
