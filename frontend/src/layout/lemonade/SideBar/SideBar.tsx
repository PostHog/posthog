import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'
import {
    IconBarChart,
    IconCohort,
    IconComment,
    IconExtension,
    IconFlag,
    IconGauge,
    IconGroupedEvents,
    IconPerson,
    IconRecording,
    IconSettings,
    IconTools,
} from '../../../lib/components/icons'
import { LemonButton } from '../../../lib/components/LemonButton'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { Link } from '../../../lib/components/Link'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { canViewPlugins } from '../../../scenes/plugins/access'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import { urls } from '../../../scenes/urls'
import { ToolbarModal } from '../../ToolbarModal/ToolbarModal'
import { lemonadeLogic } from '../lemonadeLogic'
import './SideBar.scss'

export function ProjectSwitcher(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    return (
        <div className="ProjectSwitcher">
            <div className="SideBar__heading">Project</div>
            <LemonButton icon={<Lettermark name={currentOrganization?.name} />} fullWidth type="stealth">
                <strong>{currentTeam?.name}</strong>
            </LemonButton>
        </div>
    )
}

function Spacer(): JSX.Element {
    return <div className="SideBar__spacer" />
}

function PageButton({
    title,
    icon,
    identifier,
    to,
    onClick,
}: {
    title: string
    icon: React.ReactElement
    identifier: string
    to?: string
    onClick?: () => void
}): JSX.Element {
    const { aliasedActiveScene } = useValues(sceneLogic)

    const isActive = identifier === aliasedActiveScene

    return (
        <Link to={to} onClick={onClick}>
            <LemonButton icon={icon} fullWidth type={isActive ? 'highlighted' : 'stealth'}>
                {title}
            </LemonButton>
        </Link>
    )
}

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { showToolbarModal } = useActions(lemonadeLogic)

    return (
        <div className="Pages">
            {currentOrganization?.setup.is_active && (
                <>
                    <PageButton
                        title="Setup"
                        icon={<IconSettings />}
                        identifier="onboardingSetup"
                        to={urls.onboardingSetup()}
                    />
                    <Spacer />
                </>
            )}
            <PageButton title="Dashboards" icon={<IconGauge />} identifier="dashboards" to={urls.dashboards()} />
            <PageButton title="Insights" icon={<IconBarChart />} identifier="savedInsights" to={urls.savedInsights()} />
            <PageButton
                title="Recordings"
                icon={<IconRecording />}
                identifier="sessionRecordings"
                to={urls.sessionRecordings()}
            />
            <PageButton title="Feature flags" icon={<IconFlag />} identifier="featureFlags" to={urls.featureFlags()} />
            <Spacer />
            <PageButton title="Events & actions" icon={<IconGroupedEvents />} identifier="events" to={urls.events()} />
            <PageButton title="Persons" icon={<IconPerson />} identifier="persons" to={urls.persons()} />
            <PageButton title="Cohorts" icon={<IconCohort />} identifier="cohorts" to={urls.cohorts()} />
            <PageButton title="Annotations" icon={<IconComment />} identifier="annotations" to={urls.annotations()} />
            <Spacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton title="Plugins" icon={<IconExtension />} identifier="plugins" to={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="toolbar" onClick={showToolbarModal} />
            <PageButton
                title="Project settings"
                icon={<IconSettings />}
                identifier="projectSettings"
                to={urls.projectSettings()}
            />
        </div>
    )
}

export function SideBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { isSideBarShown, isToolbarModalShown } = useValues(lemonadeLogic)
    const { hideSideBar, hideToolbarModal } = useActions(lemonadeLogic)

    return (
        <div className={clsx('SideBar', 'SideBar__layout', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__content">
                    <ProjectSwitcher />
                    <Spacer />
                    <Pages />
                </div>
            </div>
            <div className="SideBar__overlay" onClick={hideSideBar} />
            {children}
            <ToolbarModal visible={isToolbarModalShown} onCancel={hideToolbarModal} />
        </div>
    )
}
