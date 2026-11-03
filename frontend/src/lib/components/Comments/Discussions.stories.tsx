import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

import discussionsJson from './__mocks__/discussions.json'
import { CommentComposer } from './CommentComposer'
import { CommentsList } from './CommentsList'
import { CommentsLogicProps, commentsLogic } from './commentsLogic'
import { linkSlackThreadLogic } from './linkSlackThreadLogic'

const LOGIC_PROPS: CommentsLogicProps = { scope: ActivityScope.INSIGHT, item_id: '12345' }

type StoryArgs = { replyingTo?: string; linkingSlackThread?: boolean }

function DiscussionsPanel({ replyingTo, linkingSlackThread }: StoryArgs): JSX.Element {
    const { setReplyingComment } = useActions(commentsLogic(LOGIC_PROPS))
    const { openModal: openLinkSlackThread } = useActions(linkSlackThreadLogic(LOGIC_PROPS))

    useOnMountEffect(() => {
        if (replyingTo) {
            setReplyingComment(replyingTo)
        }
        if (linkingSlackThread) {
            openLinkSlackThread()
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

// A discussion that started in Slack and was linked here: the opening message has arrived, its earlier
// replies haven't yet, so the note says they are on their way.
const LINKED_SLACK_THREAD = {
    next: null,
    previous: null,
    results: [
        {
            id: 'linked-0001',
            created_by: null,
            deleted: false,
            content: 'Has anyone seen exports stall like this?',
            rich_content: null,
            version: 0,
            created_at: '2025-10-08T09:10:36.000Z',
            item_id: '12345',
            item_context: { from_slack: true, slack_author_name: 'Ada', slack_import_state: 'pending' },
            scope: 'Insight',
            source_comment: null,
            is_task: false,
            completed_at: null,
            completed_by: null,
            slack_thread: {
                channel_id: 'C0123ABCDEF',
                channel_name: 'team-exports',
                url: 'https://example.slack.com/archives/C0123ABCDEF/p1759914636000000',
            },
        },
    ],
}

export const LinkedSlackThread: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC] },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/comments': LINKED_SLACK_THREAD } })],
}

export const LinkSlackThreadModal: Story = {
    args: { linkingSlackThread: true },
    parameters: { featureFlags: [FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC] },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations': {
                    results: [{ id: 1, kind: 'slack', display_name: 'PostHog', config: {}, errors: null }],
                },
            },
        }),
    ],
}
