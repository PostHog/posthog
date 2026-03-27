import { Meta, StoryObj } from '@storybook/react'

import { ProjectNoticeVariant } from './navigationLogic'
import { Notice, NoticeProps, NOTICES } from './ProjectNotice'

const meta: Meta<NoticeProps> = {
    title: 'Layout/Project Notice',
    component: Notice as any,
    parameters: {
        testOptions: { width: 650, height: 250 },
    },
}
export default meta

const DEFAULT_NOTICE_PROPS: NoticeProps = {
    user: { uuid: 'test-uuid' } as NoticeProps['user'],
    altTeamForIngestion: undefined,
    showInviteModal: () => {},
    requestVerificationLink: () => {},
}

type Story = StoryObj<NoticeProps>

function noticeStoryFactory(variant: ProjectNoticeVariant, extraProps: Partial<NoticeProps> = {}): Story {
    const factory = NOTICES[variant]
    if (!factory) {
        throw new Error(`No notice factory for variant: ${variant}`)
    }

    const notice = factory({ ...DEFAULT_NOTICE_PROPS, ...extraProps })
    return {
        render: () => (
            <div className="min-w-[600px] h-full m-4">
                <Notice variant={variant} notice={notice} />
            </div>
        ),
    }
}

export const DemoProject: Story = noticeStoryFactory('demo_project')
export const DemoProjectWithAltTeam: Story = noticeStoryFactory('demo_project', {
    altTeamForIngestion: {
        id: 2,
        name: 'My Project',
        is_demo: false,
        ingested_event: false,
    } as NoticeProps['altTeamForIngestion'],
})

export const InviteTeammates: Story = noticeStoryFactory('invite_teammates')
export const UnverifiedEmail: Story = noticeStoryFactory('unverified_email')
export const InternetConnectionIssue: Story = noticeStoryFactory('internet_connection_issue')
export const EventIngestionRestriction: Story = noticeStoryFactory('event_ingestion_restriction')
export const MissingReverseProxy: Story = noticeStoryFactory('missing_reverse_proxy')
