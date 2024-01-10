import './Announcement.scss'

import { useActions, useValues } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { announcementLogic } from '~/layout/navigation/TopBar/announcementLogic'

export function Announcement(): JSX.Element | null {
    const { showAnnouncement, cloudAnnouncement } = useValues(announcementLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    if (!showAnnouncement) {
        return null
    }

    return (
        <div className="Announcement">
            <LemonMarkdown className="strong">{cloudAnnouncement as string}</LemonMarkdown>
            <div className="Announcement__close" onClick={hideAnnouncement}>
                <IconClose />
            </div>
        </div>
    )
}
