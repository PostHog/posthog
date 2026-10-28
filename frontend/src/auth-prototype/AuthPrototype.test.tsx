import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { mountSupportRouter } from 'scenes/mountSupportRouter'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { AuthPrototype } from './AuthPrototype'

jest.mock('kea', () => ({ useActions: jest.fn(), useMountedLogic: jest.fn(), useValues: jest.fn() }))
jest.mock('@base-ui/react/tooltip', () => ({
    Tooltip: { Provider: ({ children }: { children: ReactNode }) => children },
}))
jest.mock('@posthog/react', () => ({ PostHogProvider: ({ children }: { children: ReactNode }) => children }))
jest.mock('react-toastify', () => ({ ToastContainer: () => null, Slide: () => null }))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ ToastCloseButton: () => null }))
jest.mock('lib/lemon-ui/LemonButton', () => ({
    LemonButton: ({ children, onClick }: { children: ReactNode; onClick: () => void }) => (
        <button onClick={onClick}>{children}</button>
    ),
}))
jest.mock('scenes/authentication/auth/Auth', () => ({ Auth: () => <div>Login form</div> }))
jest.mock('scenes/authentication/auth/authLogic', () => ({ authLogic: {} }))
jest.mock('scenes/PreflightCheck/preflightLogic', () => ({ preflightLogic: {} }))
jest.mock('scenes/userLogic', () => ({ userLogic: {} }))
jest.mock('scenes/mountSupportRouter', () => ({
    mountSupportRouter: jest.fn(() => ({ unmount: jest.fn() })),
}))
jest.mock('./authPrototypeLogic', () => ({ authPrototypeLogic: {} }))

describe('standalone login state', () => {
    const originalMark = Object.getOwnPropertyDescriptor(performance, 'mark')
    const loadPreflight = jest.fn()
    let preflight: object | null
    let preflightLoading: boolean
    let user: object | null
    let userLoading: boolean

    beforeEach(() => {
        preflight = null
        preflightLoading = true
        user = null
        userLoading = false
        loadPreflight.mockClear()
        jest.mocked(mountSupportRouter).mockClear()
        ;(useValues as jest.Mock).mockImplementation((logic) =>
            logic === preflightLogic ? { preflight, preflightLoading } : { user, userLoading }
        )
        ;(useActions as jest.Mock).mockReturnValue({ loadPreflight })
        Object.defineProperty(performance, 'mark', { configurable: true, value: jest.fn() })
    })

    afterEach(() => {
        cleanup()
        window.history.replaceState(null, '', '/')
        if (originalMark) {
            Object.defineProperty(performance, 'mark', originalMark)
        } else {
            Reflect.deleteProperty(performance, 'mark')
        }
    })

    it('waits for preflight, then offers retry on failure', () => {
        const view = render(<AuthPrototype />)
        expect(screen.getByRole('status')).toHaveTextContent('Loading login')
        expect(screen.queryByText('Login form')).not.toBeInTheDocument()

        preflightLoading = false
        view.rerender(<AuthPrototype />)
        expect(screen.getByRole('alert')).toHaveTextContent('Login could not load')
        fireEvent.click(screen.getByText('Try again'))
        expect(loadPreflight).toHaveBeenCalledTimes(1)

        preflight = { can_create_org: true }
        view.rerender(<AuthPrototype />)
        expect(screen.getByText('Login form')).toBeInTheDocument()
    })

    it('keeps the login form hidden when a user has loaded', () => {
        preflight = { can_create_org: true }
        preflightLoading = false
        user = { id: 1 }
        render(<AuthPrototype />)

        expect(screen.queryByText('Login form')).not.toBeInTheDocument()
        expect(mountSupportRouter).not.toHaveBeenCalled()
    })

    it.each(['#panel=support', '#supportModal=support'])(
        'waits for login readiness before starting support for %s',
        (hash) => {
            window.history.replaceState(null, '', `/login${hash}`)
            const view = render(<AuthPrototype />)
            expect(screen.queryByText('Login form')).not.toBeInTheDocument()
            expect(mountSupportRouter).not.toHaveBeenCalled()

            preflightLoading = false
            view.rerender(<AuthPrototype />)
            expect(screen.getByRole('alert')).toHaveTextContent('Login could not load')
            expect(mountSupportRouter).not.toHaveBeenCalled()

            preflight = { cloud: true, can_create_org: true }
            preflightLoading = true
            view.rerender(<AuthPrototype />)
            expect(screen.queryByText('Login form')).not.toBeInTheDocument()
            expect(mountSupportRouter).not.toHaveBeenCalled()

            preflightLoading = false
            userLoading = true
            view.rerender(<AuthPrototype />)
            expect(screen.queryByText('Login form')).not.toBeInTheDocument()
            expect(mountSupportRouter).not.toHaveBeenCalled()

            userLoading = false
            view.rerender(<AuthPrototype />)
            expect(screen.getByText('Login form')).toBeInTheDocument()
            expect(mountSupportRouter).toHaveBeenCalledTimes(1)
            expect(window.location.hash).toBe(hash)

            view.rerender(<AuthPrototype />)
            expect(mountSupportRouter).toHaveBeenCalledTimes(1)
        }
    )
})
