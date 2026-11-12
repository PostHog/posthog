import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import discussionsJson from 'lib/components/Comments/__mocks__/discussions.json'
import { CommentsLogicProps, commentsLogic } from 'lib/components/Comments/commentsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

import { QuillDiscussion } from './QuillDiscussion'

const LOGIC_PROPS: CommentsLogicProps = { scope: ActivityScope.INSIGHT, item_id: '12345' }

type StoryArgs = { replyingTo?: string }

function Discussion({ replyingTo }: StoryArgs): JSX.Element {
    const { setReplyingComment } = useActions(commentsLogic(LOGIC_PROPS))

    useOnMountEffect(() => {
        if (replyingTo) {
            setReplyingComment(replyingTo)
        }
    })

    return (
        // The docked panel's default width, so the story shows the narrow case.
        <div className="flex h-[640px] w-[340px] flex-col rounded-lg border border-border bg-card">
            <QuillDiscussion logicProps={LOGIC_PROPS} />
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Layout/Side panel/Quill discussion',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2025-10-10',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [], waitForSelector: '[data-attr="discussions-thread"]' },
        msw: { mocks: { get: { '/api/projects/:team_id/comments': discussionsJson } } },
    },
    decorators: [mswDecorator({})],
    render: (args) => <Discussion {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const Threads: Story = {}

export const ReplyingToThread: Story = {
    args: { replyingTo: 'thread-0001' },
}

export const NoComments: Story = {
    parameters: {
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=No comments yet' },
        msw: { mocks: { get: { '/api/projects/:team_id/comments': { next: null, previous: null, results: [] } } } },
    },
}
