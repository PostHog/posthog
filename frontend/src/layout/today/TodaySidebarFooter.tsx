import { useValues } from 'kea'

import { IconChevronDown, IconGear } from '@posthog/icons'
import { Avatar, AvatarFallback, Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { ProjectCombobox } from 'lib/components/Account/ProjectCombobox'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function TodaySidebarFooter(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectName = currentTeam?.name ?? 'Project'

    return (
        <div className="flex items-center gap-2 border-t border-border p-2">
            <Popover>
                <PopoverTrigger
                    render={
                        <Button
                            left
                            className="min-w-0 flex-1"
                            aria-label={`Project: ${projectName}`}
                            data-attr="today-project-menu"
                        />
                    }
                >
                    <Avatar size="xs">
                        <AvatarFallback>
                            {String.fromCodePoint(projectName.codePointAt(0) ?? 80).toLocaleUpperCase()}
                        </AvatarFallback>
                    </Avatar>
                    <span className="min-w-0 flex-1 truncate text-start">{projectName}</span>
                    <IconChevronDown />
                </PopoverTrigger>
                <PopoverContent align="start" side="top" className="min-w-70">
                    {/* The project picker is shared with the flag-off navigation, so it stays on LemonUI. */}
                    <div data-not-quill>
                        <ProjectCombobox />
                    </div>
                </PopoverContent>
            </Popover>
            <Button render={<LinkPrimitive to={urls.settings('project')} />} data-attr="today-settings">
                <IconGear />
                Settings
            </Button>
        </div>
    )
}
