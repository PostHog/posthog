import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { CommentComposer } from './CommentComposer'

import { useStorybookMocks } from '~/mocks/browser'

type Story = StoryObj<typeof CommentComposer>

const meta: Meta<typeof CommentComposer> = {
    title: 'Components/Comments/CommentComposer',
    component: CommentComposer,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

const Template: StoryFn<typeof CommentComposer> = (args) => {
    useStorybookMocks({
        post: {
            '/api/projects/:team_id/comments': (req, res, ctx) => {
                const body = req.body as any
                return res(
                    ctx.json({
                        id: 'new-comment-1',
                        content: body.content,
                        rich_content: body.rich_content,
                        version: 0,
                        created_at: new Date().toISOString(),
                        created_by: {
                            id: 1,
                            uuid: 'user-1',
                            distinct_id: 'user-1',
                            first_name: 'Current',
                            last_name: 'User',
                            email: 'user@example.com',
                            is_email_verified: true,
                        },
                        scope: body.scope,
                        item_id: body.item_id,
                        item_context: body.item_context,
                        source_comment: body.source_comment,
                    })
                )
            },
        },
    })

    return <CommentComposer {...args} />
}

export const Default: Story = {
    render: Template,
    args: {
        scope: 'Insight',
        item_id: 'insight-123',
    },
}

export const ReplyMode: Story = {
    render: Template,
    args: {
        scope: 'Comment',
        item_id: 'comment-123',
    },
    decorators: [
        (Story) => {
            // Simulate reply state
            return <Story />
        },
    ],
}

export const FeatureFlagScope: Story = {
    render: Template,
    args: {
        scope: 'FeatureFlag',
        item_id: 'flag-123',
    },
}

export const ExperimentScope: Story = {
    render: Template,
    args: {
        scope: 'Experiment',
        item_id: 'experiment-123',
    },
}

export const DisabledComposer: Story = {
    render: Template,
    args: {
        scope: 'Insight',
        item_id: 'insight-123',
        disabled: true,
    },
}

export const WithoutItemId: Story = {
    render: Template,
    args: {
        scope: 'Dashboard',
    },
}
