import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'

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

    it('opens a new evaluation from the clicked template', () => {
        const container = renderWithAccess(AccessControlLevel.Editor)

        container.querySelector<HTMLButtonElement>('[data-attr="evaluation-template-sentiment"]')!.click()

        expect(router.values.location.pathname).toContain('/evaluations/new')
        expect(router.values.searchParams.template).toEqual('sentiment')
    })

    it('shows no templates to a user who cannot create evaluations', () => {
        const container = renderWithAccess(AccessControlLevel.Viewer)

        expect(container.querySelector('[data-attr^="evaluation-template-"]')).toBeNull()
    })
})
