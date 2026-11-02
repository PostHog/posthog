import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { ImpersonationNoticeSlot } from './ImpersonationNoticeSlot'

jest.mock('./ImpersonationNotice', () => ({
    ImpersonationNotice: () => <div>impersonation notice</div>,
}))

describe('ImpersonationNoticeSlot', () => {
    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
    })

    afterEach(cleanup)

    it('keeps the notice mounted after impersonation ends', async () => {
        act(() => userLogic.actions.loadUserSuccess({ is_impersonated: false } as any))
        render(<ImpersonationNoticeSlot />)
        expect(screen.queryByText('impersonation notice')).not.toBeInTheDocument()

        act(() => userLogic.actions.loadUserSuccess({ is_impersonated: true } as any))
        expect(await screen.findByText('impersonation notice')).toBeInTheDocument()

        act(() => userLogic.actions.loadUserSuccess({ is_impersonated: false } as any))
        expect(screen.getByText('impersonation notice')).toBeInTheDocument()
    })
})
