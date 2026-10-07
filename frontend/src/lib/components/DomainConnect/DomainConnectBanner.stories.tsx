import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { DomainConnectBanner } from './DomainConnectBanner'

const meta: Meta<typeof DomainConnectBanner> = {
    title: 'Components/Domain Connect',
    component: DomainConnectBanner,
    tags: ['test-skip-chromium'],
    args: { logicKey: 'mobile-cloudflare', domain: 'example.com', context: 'proxy', proxyRecordId: 'example-proxy' },
    render: (args) => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/integrations/domain-connect/check/': () => [
                    200,
                    { supported: true, provider_name: 'Cloudflare', available_providers: [] },
                ],
            },
            post: {
                '/api/projects/:team_id/integrations/domain-connect/apply-url/': async () => {
                    await new Promise<void>((resolve) => {
                        window.addEventListener('release-domain-connect-response', () => resolve(), { once: true })
                        document.documentElement.dataset.domainConnectResponsePending = 'true'
                    })
                    return [200, { url: 'https://dns.example.com/connect' }]
                },
            },
        })
        return <DomainConnectBanner {...args} />
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const MobilePopup: Story = {}
export const MobileFallback: Story = {}
