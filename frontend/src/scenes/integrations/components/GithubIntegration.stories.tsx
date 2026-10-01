import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { GithubIntegration } from './GithubIntegration'

interface StoryArgs {
    multiple: boolean
    width: number
    unavailable: boolean
}

const meta: Meta<StoryArgs> = {
    title: 'Components/Integrations/GitHub suggestions',
    args: { multiple: false, width: 960, unavailable: false },
    render: ({ multiple, width, unavailable }): JSX.Element => {
        useStorybookMocks({
            get: {
                '/api/projects/:id/integrations': { results: [] },
                '/api/projects/:id/integrations/github/available_installations/': {
                    discovery_id: '11111111-1111-4111-8111-111111111111',
                    discovered_at: new Date().toISOString(),
                    personal_github_connected: true,
                    personal_github_login: 'synthetic-reader',
                    personal_discovery_status: unavailable ? 'unavailable' : 'ok',
                    installations: [
                        {
                            installation_id: '9001',
                            account_name: 'synthetic-owner',
                            account_type: 'Organization',
                            source_team_id: unavailable ? 7 : null,
                            source_team_name: unavailable ? 'Synthetic website' : null,
                        },
                        ...(multiple
                            ? [
                                  {
                                      installation_id: '9002',
                                      account_name: null,
                                      account_type: null,
                                      source_team_id: 7,
                                      source_team_name: 'Synthetic website',
                                  },
                              ]
                            : []),
                    ],
                },
                '/api/users/@me/integrations/github/install_requests/': {
                    results: [],
                    install_url: 'https://example.com/install',
                },
            },
        })
        return (
            <div className={width === 520 ? 'w-[520px]' : 'w-[960px]'}>
                <GithubIntegration connectSurface="settings" />
            </div>
        )
    },
}
export default meta

export const Single: StoryObj<StoryArgs> = {}
export const Multiple: StoryObj<StoryArgs> = { args: { multiple: true } }
export const Narrow: StoryObj<StoryArgs> = { args: { width: 520, multiple: true } }
export const PersonalUnavailable: StoryObj<StoryArgs> = { args: { unavailable: true, width: 520 } }
