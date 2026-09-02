import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'
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

        expect(screen.getAllByText('Choose an account')).toHaveLength(1)
        expect(screen.queryByText('PostHog')).not.toBeInTheDocument()

        await user.click(screen.getByText('Choose an account'))
        await user.click(await screen.findByText('PostHog'))

        expect(onLink).toHaveBeenCalledWith('101')
    })

    it('names the installation when only one is available', async () => {
        // Linking without an installation id asks the backend to auto-resolve from a sibling
        // project. An orphan installation has no sibling, so dropping the id here dead-ends the
        // one case adoption exists for.
        const user = userEvent.setup()
        const onLink = jest.fn()
        const installations: GitHubAvailableInstallationApi[] = [
            {
                installation_id: '303',
                account_name: 'PostHog',
                account_type: 'Organization',
                source_team_id: null,
            },
        ]

        const { container } = render(
            <GitHubInstallationLink installations={installations} loading={false} onLink={onLink} />
        )

        // Scoped to this render: the menu case above leaves its portal in the document, so a
        // `screen` query here would depend on test order.
        await user.click(within(container).getByRole('button'))

        expect(onLink).toHaveBeenCalledWith('303')
    })
})
