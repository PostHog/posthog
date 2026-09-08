import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PersonalSlackIntegrations } from './PersonalIntegrations'
import { personalIntegrationsLogic } from './personalIntegrationsLogic'

const WORKSPACE = {
    posthog_team_id: 1,
    posthog_team_name: 'Project A',
    posthog_organization_name: 'Org',
    slack_team_id: 'T123',
    slack_team_name: 'Acme',
}

describe('<PersonalSlackIntegrations />', () => {
    const useWorkspaceMocks = (workspaces: (typeof WORKSPACE)[]): void => {
        useMocks({
            get: {
                '/api/users/@me/integrations/': () => [200, { results: [] }],
                '/api/users/@me/integrations/slack/linkable_workspaces/': () => [200, { results: workspaces }],
            },
        })
        initKeaTests()
    }

    it('points to the project settings when no workspace can be linked', async () => {
        useWorkspaceMocks([])
        render(<PersonalSlackIntegrations />)
        await expectLogic(personalIntegrationsLogic).toDispatchActions(['loadLinkableSlackWorkspacesSuccess'])

        expect(screen.queryByText('Link my Slack account')).not.toBeInTheDocument()
        expect(await screen.findByText('project settings, under Integrations')).toHaveAttribute(
            'href',
            expect.stringContaining('/settings/environment-integrations#integration-slack')
        )
    })

    it('reports the connect click on the link button', async () => {
        useWorkspaceMocks([WORKSPACE])
        render(<PersonalSlackIntegrations />)
        await expectLogic(personalIntegrationsLogic).toDispatchActions(['loadLinkableSlackWorkspacesSuccess'])

        await expectLogic(eventUsageLogic, () =>
            userEvent.click(screen.getByText('Link my Slack account'))
        ).toDispatchActions([eventUsageLogic.actionCreators.reportPersonalIntegrationConnectClicked('slack')])
    })
})
