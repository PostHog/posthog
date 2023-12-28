import './SideBar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { DebugNotice } from 'lib/components/DebugNotice'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { NotebookPopover } from 'scenes/notebooks/NotebookPanel/NotebookPopover'

import { ProjectName, ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { PageButton } from '~/layout/navigation/SideBar/PageButton'
import { organizationLogic } from '~/scenes/organizationLogic'
import { Scene } from '~/scenes/sceneTypes'
import { isAuthenticatedTeam, teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'

import { navigationLogic } from '../navigationLogic'

function Pages(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { toggleProjectSwitcher, hideProjectSwitcher } = useActions(navigationLogic)
    const { isProjectSwitcherShown } = useValues(navigationLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <ul>
            <PageButton
                title={
                    isAuthenticatedTeam(currentTeam) ? (
                        <>
                            <span>
                                <ProjectName team={currentTeam} />
                            </span>
                        </>
                    ) : (
                        'Choose project'
                    )
                }
                icon={<Lettermark name={currentOrganization?.name} />}
                identifier={Scene.ProjectHomepage}
                to={urls.projectHomepage()}
                sideAction={{
                    'aria-label': 'switch project',
                    onClick: () => toggleProjectSwitcher(),
                    dropdown: {
                        visible: isProjectSwitcherShown,
                        onClickOutside: hideProjectSwitcher,
                        overlay: <ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />,
                        actionable: true,
                    },
                }}
            />
        </ul>
    )
}

export function SideBar(): JSX.Element {
    const { isSideBarShown } = useValues(navigationLogic)

    return (
        <div className={clsx('SideBar', !isSideBarShown && 'SideBar--hidden')}>
            <div className="SideBar__slider">
                <div className="SideBar__slider__content">
                    <Pages />
                    <DebugNotice />
                </div>
            </div>
            <NotebookPopover />
            <ActivationSidebar />
        </div>
    )
}
