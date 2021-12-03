import React, { Fragment } from 'react'
import ReactMarkdown from 'react-markdown'
import clsx from 'clsx'
import { CloseOutlined } from '@ant-design/icons'
import { MOCK_NODE_PROCESS } from 'lib/constants'
import { announcementLogic, AnnouncementType } from '~/layout/navigation/TopBar/announcementLogic'
import { useActions, useValues } from 'kea'
import { GroupsIntroductionBanner } from 'lib/introductions/GroupsIntroductionBanner'

window.process = MOCK_NODE_PROCESS

export function Announcement(): JSX.Element | null {
    const { relevantAnnouncementType, cloudAnnouncement } = useValues(announcementLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    let message = <Fragment />
    if (relevantAnnouncementType === AnnouncementType.CloudFlag && cloudAnnouncement) {
        message = <ReactMarkdown className="strong">{cloudAnnouncement}</ReactMarkdown>
    } else if (relevantAnnouncementType === AnnouncementType.GroupAnalytics) {
        message = <GroupsIntroductionBanner />
    }

    return (
        <div className={clsx('Announcement', !relevantAnnouncementType && 'Announcement--hidden')}>
            {message}

            <CloseOutlined className="Announcement__close" onClick={() => hideAnnouncement(relevantAnnouncementType)} />
        </div>
    )
}
