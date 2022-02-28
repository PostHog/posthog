import React from 'react'
import { LinkButton } from 'lib/components/LinkButton'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { useActions, useValues } from 'kea'
import { CloseOutlined } from '@ant-design/icons'
import clsx from 'clsx'
import { announcementLogic } from '~/layout/navigation/TopBar/announcementLogic'
import { userLogic } from 'scenes/userLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationMembershipLevel } from 'lib/constants'

export function AttentionRequiredBanner(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { overview, systemStatusLoading } = useValues(systemStatusLogic)
    const { shownAnnouncementType, closable } = useValues(announcementLogic)
    const { hideAnnouncement } = useActions(announcementLogic)

    const areAsyncMigrationsUpToDate = overview.find((metric) => metric.key === 'async_migrations_ok')
    const isUserAdmin = user?.is_staff || currentOrganization?.membership_level === OrganizationMembershipLevel.Admin
    const loadingData = systemStatusLoading || currentOrganizationLoading

    if (loadingData || areAsyncMigrationsUpToDate || !isUserAdmin) {
        return null
    }

    return (
        <div className={clsx('Announcement', !shownAnnouncementType && 'Announcement--hidden')}>
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
            {closable && (
                <CloseOutlined
                    className="Announcement__close"
                    onClick={() => hideAnnouncement(shownAnnouncementType)}
                />
            )}
        </div>
    )
}
