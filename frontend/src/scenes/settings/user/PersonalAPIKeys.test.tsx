import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EditKeyModal } from './PersonalAPIKeys'
import { personalAPIKeysLogic } from './personalAPIKeysLogic'

describe('<EditKeyModal />', () => {
    let logic: ReturnType<typeof personalAPIKeysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/personal_api_keys/': [],
                '/api/projects/': { results: [], count: 0, next: null, previous: null },
            },
        })

        initKeaTests()
        featureFlagLogic.mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        themeLogic.mount()

        logic = personalAPIKeysLogic()
        logic.mount()
    })

    const createButton = (): HTMLButtonElement => screen.getByText('Create key').closest('button') as HTMLButtonElement

    it('keeps the create button clickable and surfaces an inline error instead of a dead click', async () => {
        render(<EditKeyModal />)
        logic.actions.setEditingKeyId('new')

        const label = await screen.findByPlaceholderText(/Reports bot/i)
        await userEvent.type(label, 'Reports bot')

        // The button used to be aria-disabled while access mode was unset, so the click did nothing.
        expect(createButton()).not.toHaveAttribute('aria-disabled', 'true')

        await userEvent.click(createButton())

        expect(await screen.findByText('Select access mode')).toBeInTheDocument()
    })
})
