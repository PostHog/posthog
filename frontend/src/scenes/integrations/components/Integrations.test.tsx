import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { GitHubInstallationLink } from './Integrations'

describe('GitHubInstallationLink', () => {
    it('uses one menu trigger when multiple GitHub installations are available', async () => {
        const user = userEvent.setup()
        const onLink = jest.fn()
        const installations: GitHubAvailableInstallationApi[] = [
            {
                installation_id: '101',
                account_name: 'PostHog',
                account_type: 'Organization',
                source_team_id: 1,
            },
            {
                installation_id: '202',
                account_name: 'Hedgebox',
                account_type: 'Organization',
                source_team_id: 2,
            },
        ]

        render(<GitHubInstallationLink installations={installations} loading={false} onLink={onLink} />)

        expect(screen.getAllByText('Link existing installation')).toHaveLength(1)
        expect(screen.queryByText('PostHog')).not.toBeInTheDocument()

        await user.click(screen.getByText('Link existing installation'))
        await user.click(await screen.findByText('PostHog'))

        expect(onLink).toHaveBeenCalledWith('101')
    })
})
