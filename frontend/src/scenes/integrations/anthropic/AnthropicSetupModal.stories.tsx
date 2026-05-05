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
}
export default meta

type Story = StoryObj<typeof AnthropicSetupModal>

export const Default: Story = {
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

export const WithSubmissionError: Story = {
    name: 'With submission error (DRF field error)',
    render: (args) => {
        useStorybookMocks({
            get: { '/api/projects/:id/integrations': { results: [] } },
            post: {
                '/api/projects/:id/integrations': (_req, _res, ctx) => [
                    ctx.status(400),
                    ctx.json({
                        config: ["An integration with id 'Production' already exists for this team."],
                    }),
                ],
            },
        })
        return <AnthropicSetupModal {...args} />
    },
}

export const WithDetailError: Story = {
    name: 'With submission error (top-level detail)',
    render: (args) => {
        useStorybookMocks({
            get: { '/api/projects/:id/integrations': { results: [] } },
            post: {
                '/api/projects/:id/integrations': (_req, _res, ctx) => [
                    ctx.status(400),
                    ctx.json({ detail: 'Invalid Anthropic API key' }),
                ],
            },
        })
        return <AnthropicSetupModal {...args} />
    },
}
