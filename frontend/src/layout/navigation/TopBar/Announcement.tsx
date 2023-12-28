import './Announcement.scss'

import { LemonButton, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { NewFeatureBanner } from 'lib/introductions/NewFeatureBanner'
import { IconClose } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { announcementLogic, AnnouncementType } from '~/layout/navigation/TopBar/announcementLogic'

export function Announcement(): JSX.Element | null {
    const { shownAnnouncementType, cloudAnnouncement, closable } = useValues(announcementLogic)
    const { preflight } = useValues(preflightLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    let message: JSX.Element | undefined
    if (preflight?.demo) {
        message = (
            <b>
                Welcome to PostHog's demo environment. To level up,{' '}
                <Link to="https://posthog.com/signup" target="_blank">
                    deploy your own PostHog instance, or sign up for PostHog Cloud
                </Link>
                .
            </b>
        )
    } else if (shownAnnouncementType === AnnouncementType.AttentionRequired) {
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
    } else if (shownAnnouncementType === AnnouncementType.NewFeature) {
        message = <NewFeatureBanner />
    }

    return (
        <div className={clsx('Announcement', !shownAnnouncementType && 'Announcement--hidden')}>
            {message}
            {closable && (
                <div className="Announcement__close" onClick={() => hideAnnouncement(shownAnnouncementType)}>
                    <IconClose />
                </div>
            )}
        </div>
    )
}
