import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { CommentWithReplies } from './Comment'
import { CommentType } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'

type Story = StoryObj<typeof CommentWithReplies>

const meta: Meta<typeof CommentWithReplies> = {
    title: 'Components/Comments/Comment',
    component: CommentWithReplies,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

const baseComment: CommentType = {
    id: 'comment-1',
    content: 'This is a plain text comment',
    rich_content: null,
    version: 0,
    created_at: '2024-01-15T10:00:00Z',
    created_by: {
        id: 1,
        uuid: 'user-1',
        distinct_id: 'user-1',
        first_name: 'John',
        last_name: 'Doe',
        email: 'john@example.com',
        is_email_verified: true,
    },
    scope: 'Insight',
    item_id: 'insight-123',
    item_context: null,
}

const richContentExample = {
    type: 'doc',
    content: [
        {
            type: 'paragraph',
            content: [
                { type: 'text', text: 'This is a ' },
                { type: 'text', marks: [{ type: 'bold' }], text: 'rich text' },
                { type: 'text', text: ' comment with ' },
                { type: 'text', marks: [{ type: 'italic' }], text: 'formatting' },
                { type: 'text', text: '.' },
            ],
        },
        {
            type: 'paragraph',
            content: [{ type: 'text', text: 'It supports multiple paragraphs and more!' }],
        },
    ],
}

const Template: StoryFn<typeof CommentWithReplies> = (args) => {
    useStorybookMocks({
        get: {},
        post: {
            '/api/projects/:team_id/comments/:id': (_, res, ctx) => {
                return res(ctx.json({ ...baseComment, content: 'Updated comment' }))
            },
        },
        patch: {
            '/api/projects/:team_id/comments/:id': (_, res, ctx) => {
                return res(ctx.json({ ...baseComment, content: 'Updated comment', version: 1 }))
            },
        },
    })

    return <CommentWithReplies {...args} />
}

export const PlainTextComment: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-1',
            comment: baseComment,
            replies: [],
        },
    },
}

export const RichTextComment: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-2',
            comment: {
                ...baseComment,
                id: 'comment-2',
                content: 'This is a rich text comment',
                rich_content: richContentExample,
            },
            replies: [],
        },
    },
}

export const EditedComment: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-3',
            comment: {
                ...baseComment,
                id: 'comment-3',
                content: 'This comment has been edited',
                version: 2,
            },
            replies: [],
        },
    },
}

export const CommentWithReplies: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-4',
            comment: {
                ...baseComment,
                id: 'comment-4',
                content: 'This is the main comment',
            },
            replies: [
                {
                    ...baseComment,
                    id: 'reply-1',
                    content: 'This is a reply',
                    source_comment: 'comment-4',
                    created_by: {
                        ...baseComment.created_by!,
                        id: 2,
                        uuid: 'user-2',
                        distinct_id: 'user-2',
                        first_name: 'Jane',
                        email: 'jane@example.com',
                    },
                },
                {
                    ...baseComment,
                    id: 'reply-2',
                    content: 'This is another reply with rich content',
                    rich_content: richContentExample,
                    source_comment: 'comment-4',
                },
            ],
        },
    },
}

export const DeletedComment: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-5',
            comment: undefined,
            replies: [],
        },
    },
}

export const CommentWithImage: Story = {
    render: Template,
    args: {
        commentWithReplies: {
            id: 'comment-6',
            comment: {
                ...baseComment,
                id: 'comment-6',
                content: 'Comment with an image',
                rich_content: {
                    type: 'doc',
                    content: [
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: 'Check out this screenshot:' }],
                        },
                        {
                            type: 'image',
                            attrs: {
                                src: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
                                alt: 'A tiny red dot',
                            },
                        },
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: 'Pretty cool, right?' }],
                        },
                    ],
                },
            },
            replies: [],
        },
    },
}
