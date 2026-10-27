import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { EvaluationQuickStart } from './EvaluationQuickStart'

describe('EvaluationQuickStart', () => {
    const originalAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    const renderWithAccess = (level: AccessControlLevel): HTMLElement => {
        window.POSTHOG_APP_CONTEXT = {
            ...originalAppContext,
            resource_access_control: {
                ...originalAppContext?.resource_access_control,
                [AccessControlResourceType.Evaluation]: level,
            },
        } as AppContext
        return render(<EvaluationQuickStart mode="needs-setup" preview={false} />).container
    }

    it('offers three recommended templates and a scratch card', () => {
        const container = renderWithAccess(AccessControlLevel.Editor)

        const cards = Array.from(container.querySelectorAll('[data-attr^="evaluation-template-"]')).filter(
            (element) => !element.getAttribute('data-attr')!.startsWith('evaluation-template-example-')
        )
        expect(cards).toHaveLength(4)
        expect(cards[3]).toHaveAttribute('data-attr', 'evaluation-template-scratch')
    })

    it.each([
        ['sentiment', 'sentiment', 'sentiment'],
        ['scratch', undefined, 'blank'],
    ])('opens a new evaluation from the %s card', (cardKey, expectedTemplate, trackedKey) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        const container = renderWithAccess(AccessControlLevel.Editor)

        container.querySelector<HTMLButtonElement>(`[data-attr="evaluation-template-${cardKey}"]`)!.click()

        expect(router.values.location.pathname).toContain('/evaluations/new')
        expect(router.values.searchParams.template).toEqual(expectedTemplate)
        expect(capture).toHaveBeenCalledWith(
            'llm evaluation template selected',
            expect.objectContaining({ template_key: trackedKey, source: 'empty_state_quick_start' })
        )
    })

    it('shows no templates to a user who cannot create evaluations', () => {
        const container = renderWithAccess(AccessControlLevel.Viewer)

        expect(container.querySelector('[data-attr^="evaluation-template-"]')).toBeNull()
    })
})
