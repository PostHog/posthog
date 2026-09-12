import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { initKeaTests } from '~/test/init'

import { AuthorizedUrlsStep } from './AuthorizedUrlsStep'

describe('AuthorizedUrlsStep', () => {
    let logic: ReturnType<typeof authorizedUrlListLogic.build>

    beforeEach(() => {
        initKeaTests(false)
        logic = authorizedUrlListLogic({
            actionId: null,
            experimentId: null,
            productTourId: null,
            type: AuthorizedUrlListType.WEB_ANALYTICS,
            allowWildCards: false,
        })
        logic.mount()
        logic.actions.setAuthorizedUrls([])
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('explains the requirement and opens the form when Continue is blocked', () => {
        const onContinue = jest.fn()

        render(<AuthorizedUrlsStep onContinue={onContinue} onSkip={jest.fn()} />)
        fireEvent.click(screen.getByText('Continue'))

        expect(onContinue).not.toHaveBeenCalled()
        expect(screen.getByText(/Add one URL to continue/)).not.toBeNull()
        expect(logic.values.isAddUrlFormVisible).toBe(true)
    })

    it('commits the typed URL and continues from the one Continue button', async () => {
        const onContinue = jest.fn()

        render(<AuthorizedUrlsStep onContinue={onContinue} onSkip={jest.fn()} />)
        fireEvent.click(screen.getByText('Add new authorized URL'))
        fireEvent.change(screen.getByPlaceholderText(/Enter a URL/), { target: { value: 'https://example.com' } })
        expect(screen.queryByText('Save')).toBeNull()
        fireEvent.click(screen.getByText('Continue'))

        await waitFor(() => expect(onContinue).toHaveBeenCalledTimes(1))
        expect(logic.values.authorizedUrls).toContain('https://example.com')
    })
})
