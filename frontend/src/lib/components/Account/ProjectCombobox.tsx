import { useActions, useValues } from 'kea'

import { IconCheck, IconGear, IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { Label } from 'lib/ui/Label/Label'
import { MenuSeparator } from 'lib/ui/Menus/Menus'
import { getProjectSwitchTargetUrl } from 'lib/utils/router-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { AvailableFeature } from '~/types'

import { ProjectName } from './ProjectMenu'

export function ProjectCombobox(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization, projectCreationForbiddenReason } = useValues(organizationLogic)

    if (!isAuthenticatedTeam(currentTeam)) {
        return null
    }

    return (
        <Combobox>
            <Combobox.Search placeholder="Filter projects..." />
            <Combobox.Content>
                <Label intent="menu" className="px-2">
                    Current project
                </Label>
                <MenuSeparator />

                <Combobox.Empty>No projects found</Combobox.Empty>

                <Combobox.Group value={[currentTeam.name]}>
                    <ButtonGroupPrimitive fullWidth>
                        <Combobox.Item asChild>
                            <ButtonPrimitive
                                menuItem
                                active
                                hasSideActionRight
                                tooltip={`Current project: ${currentTeam.name}`}
                                tooltipPlacement="right"
                                data-attr="tree-navbar-project-dropdown-current-project-button"
                                className="pr-12"
                            >
                                <IconCheck className="text-tertiary" />
                                <ProjectName team={currentTeam} />
                            </ButtonPrimitive>
                        </Combobox.Item>

                        <Combobox.Item asChild>
                            <Link
                                buttonProps={{
                                    iconOnly: true,
                                    isSideActionRight: true,
                                }}
                                tooltip={`View settings for project: ${currentTeam.name}`}
                                tooltipPlacement="right"
                                to={urls.project(currentTeam.id, urls.settings('project'))}
                                data-attr="tree-navbar-project-dropdown-current-project-settings-button"
                            >
                                <IconGear className="text-tertiary" />
                            </Link>
                        </Combobox.Item>
                    </ButtonGroupPrimitive>
                </Combobox.Group>

                {currentOrganization &&
                    currentOrganization?.teams?.filter((team) => team.id !== currentTeam?.id).length > 0 && (
                        <>
                            <Label intent="menu" className="px-2 mt-2">
                                Other projects
                            </Label>
                            <MenuSeparator />
                        </>
                    )}

                {currentOrganization?.teams
                    .filter((team) => team.id !== currentTeam?.id)
                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                    .map((team) => {
                        const relativeOtherProjectPath = getProjectSwitchTargetUrl(
                            location.pathname,
                            team.id,
                            currentTeam?.project_id,
                            team.project_id
                        )

                        return (
                            <Combobox.Group value={[team.name]} key={team.id}>
                                <ButtonGroupPrimitive menuItem fullWidth>
                                    <Combobox.Item asChild>
                                        <Link
                                            buttonProps={{
                                                menuItem: true,
                                                hasSideActionRight: true,
                                                className: 'pr-12',
                                            }}
                                            tooltip={`Switch to project: ${team.name}`}
                                            tooltipPlacement="right"
                                            to={relativeOtherProjectPath}
                                            data-attr="tree-navbar-project-dropdown-other-project-button"
                                        >
                                            <IconBlank />
                                            <ProjectName team={team} />
                                        </Link>
                                    </Combobox.Item>

                                    <Combobox.Item asChild>
                                        <Link
                                            buttonProps={{
                                                iconOnly: true,
                                                isSideActionRight: true,
                                            }}
                                            tooltip={`View settings for project: ${team.name}`}
                                            tooltipPlacement="right"
                                            to={urls.project(team.id, urls.settings('project'))}
                                            data-attr="tree-navbar-project-dropdown-other-project-settings-button"
                                        >
                                            <IconGear />
                                        </Link>
                                    </Combobox.Item>
                                </ButtonGroupPrimitive>
                            </Combobox.Group>
                        )
                    })}
                <MenuSeparator />
                {preflight?.can_create_org && (
                    <Combobox.Item
                        asChild
                        onClick={() =>
                            guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                                currentUsage: currentOrganization?.teams?.length,
                            })
                        }
                    >
                        <ButtonPrimitive
                            menuItem
                            data-attr="new-project-button"
                            tooltip="Create a new project"
                            tooltipPlacement="right"
                            className="shrink-0"
                            disabled={!!projectCreationForbiddenReason}
                        >
                            <IconPlusSmall className="text-tertiary" />
                            New project
                        </ButtonPrimitive>
                    </Combobox.Item>
                )}
            </Combobox.Content>
        </Combobox>
    )
}
