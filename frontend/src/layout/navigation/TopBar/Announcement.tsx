import React from 'react'
import ReactMarkdown from 'react-markdown'
import clsx from 'clsx'
import { CloseOutlined } from '@ant-design/icons'
import { MOCK_NODE_PROCESS } from 'lib/constants'
import { announcementLogic, AnnouncementType } from '~/layout/navigation/TopBar/announcementLogic'
import { useActions, useValues } from 'kea'
import { NewFeatureBanner } from 'lib/introductions/NewFeatureBanner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { LinkButton } from 'lib/components/LinkButton'

window.process = MOCK_NODE_PROCESS

export function Announcement(): JSX.Element | null {
    const { shownAnnouncementType, cloudAnnouncement, closable } = useValues(announcementLogic)
    const { preflight } = useValues(preflightLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    let message: JSX.Element | undefined
    if (preflight?.demo) {
        message = (
            <b>
                Welcome to PostHog's demo environment. To level up,{' '}
                <a href="https://posthog.com/signup" target="_blank" rel="noopener">
                    deploy your own PostHog instance, or sign up for PostHog Cloud
                </a>
                .
            </b>
        )
    } else if (shownAnnouncementType === AnnouncementType.AttentionRequired) {
        message = (
            <div>
                <strong>Attention required!</strong> Your instance has uncompleted migrations that are required for the
                next release.
                <LinkButton
                    to="/instance/async_migrations"
                    className="NewFeatureAnnouncement__button"
                    data-attr="site-banner-async-migrations"
                >
                    Click here to fix
                </LinkButton>
            </div>
        )
    } else if (shownAnnouncementType === AnnouncementType.CloudFlag && cloudAnnouncement) {
        message = <ReactMarkdown className="strong">{cloudAnnouncement}</ReactMarkdown>
    } else if (shownAnnouncementType === AnnouncementType.NewFeature) {
        message = <NewFeatureBanner />
    }

    return (
        <div className={clsx('Announcement', !shownAnnouncementType && 'Announcement--hidden')}>
            {message}
            {closable && (
                <CloseOutlined
                    className="Announcement__close"
                    onClick={() => hideAnnouncement(shownAnnouncementType)}
                />
            )}
        </div>
    )
}
