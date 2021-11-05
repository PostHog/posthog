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
    IconPlus,
    IconRecording,
    IconSettings,
    IconTools,
} from '../../../lib/components/icons'
import {
    LemonButton,
    LemonButtonProps,
    LemonButtonWithSideAction,
    LemonButtonWithSideActionProps,
    SideAction,
} from '../../../lib/components/LemonButton'
import { Lettermark } from '../../../lib/components/Lettermark/Lettermark'
import { organizationLogic } from '../../../scenes/organizationLogic'
import { canViewPlugins } from '../../../scenes/plugins/access'
import { sceneLogic } from '../../../scenes/sceneLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import { urls } from '../../../scenes/urls'
import { ViewType } from '../../../types'
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

interface PageButtonProps extends Pick<LemonButtonProps, 'title' | 'icon'> {
    identifier: string
    onClick: (() => void) | string
    sideAction?: Omit<SideAction, 'type'> & { identifier: string }
}

function PageButton({ title, icon, sideAction, identifier, onClick }: PageButtonProps): JSX.Element {
    const { aliasedActiveScene } = useValues(sceneLogic)

    const isActiveSide: boolean = sideAction?.identifier === aliasedActiveScene
    const isActive: boolean = isActiveSide || identifier === aliasedActiveScene

    let sideActionInternal: LemonButtonWithSideActionProps['sideAction']
    if (sideAction) {
        sideActionInternal = { ...sideAction, type: isActiveSide ? 'highlighted' : isActive ? undefined : 'stealth' }
    }

    return (
        <LemonButtonWithSideAction
            icon={icon}
            fullWidth
            type={isActive ? 'highlighted' : 'stealth'}
            onClick={onClick}
            sideAction={sideActionInternal}
        >
            {title}
        </LemonButtonWithSideAction>
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
                        onClick={urls.onboardingSetup()}
                    />
                    <Spacer />
                </>
            )}
            <PageButton title="Dashboards" icon={<IconGauge />} identifier="dashboards" onClick={urls.dashboards()} />
            <PageButton
                title="Insights"
                icon={<IconBarChart />}
                identifier="savedInsights"
                onClick={urls.savedInsights()}
                sideAction={{
                    icon: <IconPlus />,
                    onClick: urls.insightView(ViewType.TRENDS),
                    tooltip: 'New insight',
                    identifier: 'insights',
                }}
            />
            <PageButton
                title="Recordings"
                icon={<IconRecording />}
                identifier="sessionRecordings"
                onClick={urls.sessionRecordings()}
            />
            <PageButton
                title="Feature flags"
                icon={<IconFlag />}
                identifier="featureFlags"
                onClick={urls.featureFlags()}
            />
            <Spacer />
            <PageButton
                title="Events & actions"
                icon={<IconGroupedEvents />}
                identifier="events"
                onClick={urls.events()}
            />
            <PageButton title="Persons" icon={<IconPerson />} identifier="persons" onClick={urls.persons()} />
            <PageButton title="Cohorts" icon={<IconCohort />} identifier="cohorts" onClick={urls.cohorts()} />
            <PageButton
                title="Annotations"
                icon={<IconComment />}
                identifier="annotations"
                onClick={urls.annotations()}
            />
            <Spacer />
            {canViewPlugins(currentOrganization) && (
                <PageButton title="Plugins" icon={<IconExtension />} identifier="plugins" onClick={urls.plugins()} />
            )}
            <PageButton title="Toolbar" icon={<IconTools />} identifier="toolbar" onClick={showToolbarModal} />
            <PageButton
                title="Project settings"
                icon={<IconSettings />}
                identifier="projectSettings"
                onClick={urls.projectSettings()}
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
