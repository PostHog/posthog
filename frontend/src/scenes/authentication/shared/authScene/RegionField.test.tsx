import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useValues } from 'kea'

import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

import { RegionField } from './RegionField'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

describe('RegionField', () => {
    beforeEach(() => {
        ;(useValues as jest.Mock).mockImplementation((logic: unknown) => {
            if (logic === preflightLogic) {
                return { preflight: { cloud: true, region: Region.US } }
            }
            if (logic === pendingOAuthConnectionLogic) {
                return { pendingConnection: null }
            }
            return {}
        })
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('opens the region menu from the label text', async () => {
        const user = userEvent.setup()
        render(<RegionField />)

        await user.click(screen.getByText('Data region'))

        expect(await screen.findByText('European Union')).toBeInTheDocument()
    })

    it('names the region select with the field and the selected region', () => {
        render(<RegionField />)

        const trigger = screen.getByText('United States').closest('button') as HTMLElement

        expect(trigger).toHaveAccessibleName('Data region: United States')
    })

    it('says so when the region already in use is picked again', async () => {
        const user = userEvent.setup()
        render(<RegionField />)

        await user.click(screen.getByText('Data region'))
        const menu = (await screen.findByText('European Union')).closest('.Popover') as HTMLElement
        await user.click(within(menu).getByText('United States'))

        expect(await screen.findByText('You are already on the United States region.')).toBeInTheDocument()
    })
})
