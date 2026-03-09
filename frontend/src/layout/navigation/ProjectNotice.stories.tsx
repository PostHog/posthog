import { Meta, StoryFn } from '@storybook/react'

import { ProjectNoticeVariant } from './navigationLogic'
import { Notice, NoticeProps, NOTICES } from './ProjectNotice'

const meta: Meta<typeof Notice> = {
    title: 'Layout/Project Notice',
    component: Notice,
    parameters: {
        testOptions: {
            viewport: { width: 400, height: 200 },
        },
    },
}
export default meta

const DEFAULT_NOTICE_PROPS: NoticeProps = {
    user: { uuid: 'test-uuid' } as any,
    altTeamForIngestion: undefined,
    showInviteModal: () => {},
    requestVerificationLink: () => {},
}

function noticeStory(variant: ProjectNoticeVariant, extraProps: Partial<NoticeProps> = {}): StoryFn<typeof Notice> {
    const factory = NOTICES[variant]
    if (!factory) {
        throw new Error(`No notice factory for variant: ${variant}`)
    }

    const notice = factory({ ...DEFAULT_NOTICE_PROPS, ...extraProps })
    return () => <Notice variant={variant} notice={notice} />
}

export const DemoProject: StoryFn<typeof Notice> = noticeStory('demo_project')
export const DemoProjectWithAltTeam: StoryFn<typeof Notice> = noticeStory('demo_project', {
    altTeamForIngestion: { id: 2, name: 'My Project', is_demo: false, ingested_event: false } as any,
})

export const InviteTeammates: StoryFn<typeof Notice> = noticeStory('invite_teammates')
export const UnverifiedEmail: StoryFn<typeof Notice> = noticeStory('unverified_email')
export const InternetConnectionIssue: StoryFn<typeof Notice> = noticeStory('internet_connection_issue')
export const EventIngestionRestriction: StoryFn<typeof Notice> = noticeStory('event_ingestion_restriction')
export const MissingReverseProxy: StoryFn<typeof Notice> = noticeStory('missing_reverse_proxy')
