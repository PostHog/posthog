import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

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
        expect(screen.getByRole('alert').textContent).toMatch(/Add one URL to continue/)
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

    it('commits a pending edit before it continues', async () => {
        const onContinue = jest.fn()

        logic.actions.setAuthorizedUrls(['https://example.com'])
        render(<AuthorizedUrlsStep onContinue={onContinue} onSkip={jest.fn()} />)
        act(() => logic.actions.setEditUrlIndex(0))
        fireEvent.change(screen.getByPlaceholderText(/Enter a URL/), {
            target: { value: 'https://edited.example.com' },
        })

        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Continue'))
        }).toDispatchActions([
            (action) =>
                action.type === logic.actionTypes.updateUrl && action.payload.url === 'https://edited.example.com',
        ])
        await waitFor(() => expect(onContinue).toHaveBeenCalledTimes(1))
    })

    it('stays on the step when a second URL fails validation', async () => {
        const onContinue = jest.fn()

        logic.actions.setAuthorizedUrls(['https://example.com'])
        render(<AuthorizedUrlsStep onContinue={onContinue} onSkip={jest.fn()} />)
        fireEvent.click(screen.getByText('Add new authorized URL'))
        fireEvent.change(screen.getByPlaceholderText(/Enter a URL/), { target: { value: 'example.com' } })

        await expectLogic(logic, () => {
            fireEvent.click(screen.getByText('Continue'))
        }).toDispatchActions(['submitProposedUrlFailure'])
        await act(async () => undefined)

        expect(onContinue).not.toHaveBeenCalled()
        expect(logic.values.isAddUrlFormVisible).toBe(true)
        expect(logic.values.authorizedUrls).toEqual(['https://example.com'])
    })
})
