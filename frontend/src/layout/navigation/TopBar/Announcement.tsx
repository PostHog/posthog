import './Announcement.scss'

import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { announcementLogic, AnnouncementType } from '~/layout/navigation/TopBar/announcementLogic'

export function Announcement(): JSX.Element | null {
    const { shownAnnouncementType, cloudAnnouncement } = useValues(announcementLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    let message: JSX.Element | undefined
    if (shownAnnouncementType === AnnouncementType.AttentionRequired) {
        message = (
            <div>
                <strong>Attention required!</strong> Your instance has uncompleted migrations that are required for the
                next release.
                <LemonButton to="/instance/async_migrations" data-attr="site-banner-async-migrations">
                    Click here to fix
                </LemonButton>
            </div>
        )
    } else if (shownAnnouncementType === AnnouncementType.CloudFlag && cloudAnnouncement) {
        message = <LemonMarkdown className="strong">{cloudAnnouncement}</LemonMarkdown>
    }

    return (
        <div className={clsx('Announcement', !shownAnnouncementType && 'Announcement--hidden')}>
            {message}
            <div className="Announcement__close" onClick={() => hideAnnouncement(shownAnnouncementType)}>
                <IconClose />
            </div>
        </div>
    )
}
