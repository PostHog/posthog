import { useValues } from 'kea'

import { LemonSnack } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
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

import { pendingInvitesLogic } from './pendingInvitesLogic'
import { ProjectCombobox } from './ProjectCombobox'

export function ProjectName({ team, className }: { team: TeamBasicType; className?: string }): JSX.Element {
    return (
        <div className={cn('flex items-center max-w-full', className)}>
            <span className="truncate">{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </div>
    )
}

export function PendingInviteDot({ className }: { className?: string }): JSX.Element {
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const organizationNames = pendingInvites.map((invite) => invite.organization_name)
    const title =
        organizationNames.length === 1
            ? `You have a pending invite to join ${organizationNames[0]}.`
            : `You have pending invites to join ${organizationNames.length} organizations.`

    return (
        <Tooltip title={title} placement="right">
            <span
                aria-label="Pending invite"
                className={cn('relative flex items-center justify-center size-3 shrink-0', className)}
            >
                {/* The ping halo scales to twice the dot, so the box is twice the dot to keep it off the neighbors */}
                <span className="absolute size-1.5 rounded-full bg-accent opacity-60 animate-ping" />
                <span className="relative size-1.5 rounded-full bg-accent" />
            </span>
        </Tooltip>
    )
}

export function ProjectMenu({
    buttonProps = { className: 'font-semibold' },
}: {
    buttonProps?: ButtonPrimitiveProps
}): JSX.Element | null {
    const iconOnly = buttonProps?.iconOnly ?? false
    const { currentTeam } = useValues(teamLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const hasPendingInvites = pendingInvites.length > 0

    return isAuthenticatedTeam(currentTeam) ? (
        <PopoverPrimitive>
            <PopoverPrimitiveTrigger asChild>
                <ButtonPrimitive
                    data-attr="tree-navbar-project-dropdown-button"
                    size={iconOnly ? 'base' : 'sm'}
                    iconOnly={iconOnly}
                    {...buttonProps}
                    className={cn(
                        'relative max-w-fit min-w-[40px]',
                        iconOnly ? 'min-w-auto' : '',
                        buttonProps.className
                    )}
                >
                    {iconOnly ? (
                        <div className="Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] w-5 h-5 dark:text-tertiary">
                            {String.fromCodePoint(currentTeam.name.codePointAt(0)!).toLocaleUpperCase()}
                        </div>
                    ) : (
                        <span className="truncate">{currentTeam.name ?? 'Project'}</span>
                    )}
                    {hasPendingInvites && <PendingInviteDot className={iconOnly ? 'absolute top-0 right-0' : 'ml-1'} />}
                    {!iconOnly && <MenuOpenIndicator className="ml-auto" />}
                </ButtonPrimitive>
            </PopoverPrimitiveTrigger>
            <PopoverPrimitiveContent align="start" className="min-w-[var(--radix-popper-anchor-width)] max-w-fit">
                <ProjectCombobox />
            </PopoverPrimitiveContent>
        </PopoverPrimitive>
    ) : null
}
