import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { GitLabSetupModal } from './GitLabSetupModal'

describe('GitLabSetupModal', () => {
    useMocks({
        get: {
            '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        cleanup()
    })

    it('submits the integration when the Connect button is clicked', async () => {
        const createSpy = jest.spyOn(api.integrations, 'create').mockResolvedValue({ id: 7, kind: 'gitlab' } as any)
        const onComplete = jest.fn()

        render(
            <Provider>
                <GitLabSetupModal isOpen onComplete={onComplete} />
            </Provider>
        )

        await userEvent.type(screen.getByPlaceholderText('1234567'), '1234567')
        await userEvent.type(
            screen.getByPlaceholderText('xxxxx-x_xxxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxx.xx.xxxxxxxxx'),
            'glpat-token'
        )
        await userEvent.click(screen.getByText('Connect'))

        await waitFor(() =>
            expect(createSpy).toHaveBeenCalledWith({
                kind: 'gitlab',
                config: {
                    hostname: 'https://gitlab.com',
                    project_id: '1234567',
                    project_access_token: 'glpat-token',
                },
            })
        )
        expect(onComplete).toHaveBeenCalledWith(7)
    })
})
