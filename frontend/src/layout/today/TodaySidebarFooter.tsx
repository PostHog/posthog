import { useValues } from 'kea'

import { IconChevronDown, IconGear } from '@posthog/icons'

import { ProjectCombobox } from 'lib/components/Account/ProjectCombobox'
import { Link } from 'lib/lemon-ui/Link'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function TodaySidebarFooter(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectName = currentTeam?.name ?? 'Project'

    return (
        <div className="TodaySidebarFooter">
            <PopoverPrimitive>
                <PopoverPrimitiveTrigger asChild>
                    <button type="button" className="TodaySidebarFooter__project" data-attr="today-project-menu">
                        <span className="TodaySidebarFooter__avatar" aria-hidden>
                            {String.fromCodePoint(projectName.codePointAt(0) ?? 80).toLocaleUpperCase()}
                        </span>
                        <span className="TodaySidebarFooter__projectText">
                            <small>Project</small>
                            <strong>{projectName}</strong>
                        </span>
                        <IconChevronDown />
                    </button>
                </PopoverPrimitiveTrigger>
                <PopoverPrimitiveContent align="start" side="top" className="min-w-[280px] max-w-fit">
                    <ProjectCombobox />
                </PopoverPrimitiveContent>
            </PopoverPrimitive>
            <Link
                to={urls.settings('project')}
                className="TodaySidebarFooter__settings"
                data-attr="today-settings"
                subtle
            >
                <IconGear />
                <span>Settings</span>
            </Link>
        </div>
    )
}
