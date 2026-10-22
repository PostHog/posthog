import { useActions, useValues } from 'kea'

import { IconGear, IconPlusSmall } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TodayLogo } from './TodayLogo'
import { ProjectMenuActionKey, todayProjectMenuLogic } from './todayProjectMenuLogic'
import { TodaySwitcherMenu, TodaySwitcherRow } from './TodaySwitcherMenu'

const ACTION_ROWS: Record<ProjectMenuActionKey, Pick<TodaySwitcherRow, 'label' | 'leading' | 'dataAttr'>> = {
    'project-settings': {
        label: 'Project settings',
        leading: <IconGear />,
        dataAttr: 'today-top-bar-project-settings',
    },
    'new-project': { label: 'New project', leading: <IconPlusSmall />, dataAttr: 'today-top-bar-new-project' },
}

// The default matches the old project switcher. Users with many projects that share a prefix asked for it: their
// names differ only near the end, so a narrower menu truncates the part that tells them apart.
const MENU_DEFAULT_WIDTH = 335

/** The project switcher shortcut opens this menu too. */
export function TodayProjectMenu(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentProject } = useValues(projectLogic)
    const { isProjectSwitcherOpen, projectSearchValue, projectGroups } = useValues(newAccountMenuLogic)
    const { openProjectSwitcher, closeProjectSwitcher, setProjectSearchValue } = useActions(newAccountMenuLogic)
    const { projectMenuActions } = useValues(todayProjectMenuLogic)
    const { runProjectMenuAction, switchProject } = useActions(todayProjectMenuLogic)

    return (
        <TodaySwitcherMenu
            trigger={
                <Button className="min-w-0 gap-1.5 px-1.5" data-attr="today-top-bar-project-menu">
                    {currentTeam && (
                        <TodayLogo
                            name={currentTeam.name}
                            mediaId={currentProject?.logo_media_id}
                            colorSeed={null}
                            size="trigger"
                        />
                    )}
                    <span className="max-w-48 min-w-0 truncate">{currentTeam?.name ?? 'Select project'}</span>
                </Button>
            }
            open={isProjectSwitcherOpen}
            onOpenChange={(open) => (open ? openProjectSwitcher() : closeProjectSwitcher())}
            searchValue={projectSearchValue}
            onSearchChange={setProjectSearchValue}
            searchPlaceholder="Search projects"
            noMatchLabel="No projects match your search"
            groups={projectGroups.map((group) => ({
                label: group.name ?? 'Projects',
                rows: group.projects.map(({ team }) => ({
                    value: String(team.id),
                    label: team.name,
                    leading: (
                        <TodayLogo
                            name={team.name}
                            // The org's project list carries no logos, so only the current project shows its upload.
                            mediaId={team.project_id === currentProject?.id ? currentProject.logo_media_id : null}
                            colorSeed={null}
                            size="row"
                        />
                    ),
                    dataAttr: 'today-top-bar-project-item',
                    onSelect: () => switchProject(team.id, team.project_id),
                })),
            }))}
            actions={projectMenuActions.map(({ key, disabledReason }) => ({
                value: key,
                disabledReason,
                ...ACTION_ROWS[key],
                onSelect: () => runProjectMenuAction(key),
            }))}
            selectedValue={currentTeam ? String(currentTeam.id) : null}
            defaultWidth={MENU_DEFAULT_WIDTH}
            resizeKey="today-project-menu"
        />
    )
}
