import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

import discussionsJson from './__mocks__/discussions.json'
import { CommentComposer } from './CommentComposer'
import { CommentsList } from './CommentsList'
import { CommentsLogicProps, commentsLogic } from './commentsLogic'

const LOGIC_PROPS: CommentsLogicProps = { scope: ActivityScope.INSIGHT, item_id: '12345' }

type StoryArgs = { replyingTo?: string }

function DiscussionsPanel({ replyingTo }: StoryArgs): JSX.Element {
    const { setReplyingComment } = useActions(commentsLogic(LOGIC_PROPS))

    useOnMountEffect(() => {
        if (replyingTo) {
            setReplyingComment(replyingTo)
        }
    })

    return (
        <div className="w-120 max-w-full flex flex-col gap-2">
            <CommentsList {...LOGIC_PROPS} />
            <CommentComposer {...LOGIC_PROPS} />
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-App/Discussions',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2025-10-10', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/comments': discussionsJson,
            },
        }),
    ],
    render: (args) => <DiscussionsPanel {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const Threads: Story = {}

export const ReplyingToThread: Story = {
    args: { replyingTo: 'thread-0001' },
}
