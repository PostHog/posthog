import { Meta, StoryObj } from '@storybook/react'
import { screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { canvasHostLogic } from './canvasHostLogic'
import { CanvasHostPromptDialog } from './CanvasHostPromptDialog'

const props = { canvasId: 'example-canvas', spaceId: 'example-space', sourceVersionId: 'example-version' }

const meta: Meta<typeof CanvasHostPromptDialog> = {
    component: CanvasHostPromptDialog,
    title: 'Scenes-App/Canvas/Action confirmation',
    tags: ['test-skip'],
    decorators: [
        (Story) => (
            <BindLogic logic={canvasHostLogic} props={props}>
                <Story />
            </BindLogic>
        ),
    ],
    parameters: { layout: 'fullscreen', testOptions: { viewport: { width: 900, height: 700 } } },
}
export default meta

type Story = StoryObj<typeof CanvasHostPromptDialog>

export const StartTask: Story = {
    play: async () => {
        await waitFor(() => {
            if (!canvasHostLogic.findMounted(props)) {
                throw new Error('Canvas host is not mounted yet')
            }
        })
        canvasHostLogic(props).actions.enqueuePrompt({
            kind: 'action',
            id: 'example-prompt',
            request: {
                action: {
                    verb: 'tasks.create_and_run',
                    summary: 'Start a cloud task in this space.',
                    destructive: false,
                    starts_cloud_run: true,
                    usage: '',
                },
                payload: {
                    title: 'Check the example chart',
                    description: 'Check how the example chart counts daily signups.',
                    idempotency_key: 'example-request',
                },
            },
        })
        await screen.findByRole('dialog', { name: 'Let this canvas make this change?' })
    },
}
