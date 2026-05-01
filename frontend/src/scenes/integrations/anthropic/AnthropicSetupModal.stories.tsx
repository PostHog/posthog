import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { AnthropicSetupModal } from './AnthropicSetupModal'

const meta: Meta<typeof AnthropicSetupModal> = {
    title: 'Components/Integrations/Anthropic',
    component: AnthropicSetupModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    args: {
        isOpen: true,
        onComplete: () => {},
    },
    render: (args) => {
        useStorybookMocks({
            get: { '/api/projects/:id/integrations': { results: [] } },
            post: {
                '/api/projects/:id/integrations': (_req, _res, ctx) => [
                    ctx.status(201),
                    ctx.json({
                        id: 1,
                        kind: 'anthropic',
                        config: { workspace_label: 'Production' },
                        display_name: 'Production',
                    }),
                ],
            },
        })
        return <AnthropicSetupModal {...args} />
    },
}
export default meta

type Story = StoryObj<typeof AnthropicSetupModal>

export const Default: Story = {}
