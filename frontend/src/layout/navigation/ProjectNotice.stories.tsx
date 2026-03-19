import { Meta, StoryFn } from '@storybook/react'

import { ProjectNoticeVariant } from './navigationLogic'
import { Notice, NoticeProps, NOTICES } from './ProjectNotice'

const meta: Meta<typeof Notice> = {
    title: 'Layout/Project Notice',
    component: Notice,
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

function noticeStoryFactory(
    variant: ProjectNoticeVariant,
    extraProps: Partial<NoticeProps> = {}
): StoryFn<typeof Notice> {
    const factory = NOTICES[variant]
    if (!factory) {
        throw new Error(`No notice factory for variant: ${variant}`)
    }

    const notice = factory({ ...DEFAULT_NOTICE_PROPS, ...extraProps })
    return () => (
        <div className="min-w-[600px] h-full m-4">
            <Notice variant={variant} notice={notice} />
        </div>
    )
}

export const DemoProject: StoryFn<typeof Notice> = noticeStoryFactory('demo_project')
export const DemoProjectWithAltTeam: StoryFn<typeof Notice> = noticeStoryFactory('demo_project', {
    altTeamForIngestion: {
        id: 2,
        name: 'My Project',
        is_demo: false,
        ingested_event: false,
    } as NoticeProps['altTeamForIngestion'],
})

export const InviteTeammates: StoryFn<typeof Notice> = noticeStoryFactory('invite_teammates')
export const UnverifiedEmail: StoryFn<typeof Notice> = noticeStoryFactory('unverified_email')
export const InternetConnectionIssue: StoryFn<typeof Notice> = noticeStoryFactory('internet_connection_issue')
export const EventIngestionRestriction: StoryFn<typeof Notice> = noticeStoryFactory('event_ingestion_restriction')
export const MissingReverseProxy: StoryFn<typeof Notice> = noticeStoryFactory('missing_reverse_proxy')
