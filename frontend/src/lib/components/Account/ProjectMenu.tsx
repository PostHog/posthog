import { useValues } from 'kea'

import { LemonSnack } from '@posthog/lemon-ui'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
import { cn } from 'lib/utils/css-classes'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import { TeamBasicType } from '~/types'

import { ProjectCombobox } from './ProjectCombobox'

export function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <div className="flex items-center max-w-full">
            <span className="truncate">{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </div>
    )
}

export function ProjectMenu({
    buttonProps = { className: 'font-semibold' },
}: {
    buttonProps?: ButtonPrimitiveProps
}): JSX.Element | null {
    const iconOnly = buttonProps?.iconOnly ?? false
    const { currentTeam } = useValues(teamLogic)

    return isAuthenticatedTeam(currentTeam) ? (
        <PopoverPrimitive>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive
                    data-attr="tree-navbar-project-dropdown-button"
                    size={iconOnly ? 'base' : 'sm'}
                    iconOnly={iconOnly}
                    {...buttonProps}
                    className={cn('max-w-fit min-w-[40px]', iconOnly ? 'min-w-auto' : '', buttonProps.className)}
                >
                    {iconOnly ? (
                        <div className="Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] w-5 h-5 dark:text-tertiary">
                            {String.fromCodePoint(currentTeam.name.codePointAt(0)!).toLocaleUpperCase()}
                        </div>
                    ) : (
                        <span className="truncate">{currentTeam.name ?? 'Project'}</span>
                    )}
                    {!iconOnly && <MenuOpenIndicator className="ml-auto" />}
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent align="start" className="min-w-[var(--radix-popper-anchor-width)] max-w-fit">
                <ProjectCombobox />
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    ) : null
}
