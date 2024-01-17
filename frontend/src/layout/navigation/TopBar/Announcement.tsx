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
        <div className="Announcement h-12 p-3 px-4 font-bold bg-primary text-md">
            <div className="relative w-full flex items-center">
                <LemonMarkdown className="strong">{cloudAnnouncement as string}</LemonMarkdown>
                <div
                    className="Announcement__close w-8 h-8 flex items-center justify-center rounded cursor-pointer absolute right-0 text-lg border"
                    onClick={hideAnnouncement}
                >
                    <IconClose />
                </div>
            </div>
        </div>
    )
}
