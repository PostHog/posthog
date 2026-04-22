import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { cn } from 'lib/utils/css-classes'
import { organizationLogic } from 'scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'

import { OrgModal } from './OrgModal'
import { pendingInvitesLogic } from './pendingInvitesLogic'
import { PendingInviteDot } from './ProjectMenu'
import { ProjectModal } from './ProjectModal'

// eslint-disable-next-line no-console
console.info('[memlens-stub] NewAccountMenu stubbed — trigger only, no menu')

interface AccountMenuProps {
    isLayoutNavCollapsed: boolean
}

export function NewAccountMenu({ isLayoutNavCollapsed }: AccountMenuProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const hasPendingInvites = pendingInvites.length > 0
    const { currentOrganization } = useValues(organizationLogic)
    const isAiFirst = useFeatureFlag('AI_FIRST')

    const projectNameStartsWithEmoji = currentTeam?.name?.match(/^\p{Emoji}/u) !== null
    const projectNameWithoutFirstEmoji = projectNameStartsWithEmoji
        ? currentTeam?.name?.replace(/^\p{Emoji}/u, '').trimStart()
        : currentTeam?.name

    return (
        <>
            <ButtonPrimitive
                iconOnly={isLayoutNavCollapsed}
                className={cn('relative flex-1 py-1 min-w-0 group', {
                    'pl-[3px] gap-[6px]': !isLayoutNavCollapsed,
                })}
                data-attr="new-account-menu-button"
            >
                {currentOrganization ? (
                    <UploadedLogo
                        name={currentOrganization.name}
                        entityId={currentOrganization.id}
                        mediaId={currentOrganization.logo_media_id}
                        size="small"
                    />
                ) : (
                    <UploadedLogo name="?" entityId="" mediaId="" size="xsmall" />
                )}
                {!isLayoutNavCollapsed && (
                    <span className={cn('truncate', isAiFirst && 'text-secondary group-hover:text-primary')}>
                        {isAuthenticatedTeam(currentTeam)
                            ? (projectNameWithoutFirstEmoji ?? 'Project')
                            : 'Account menu'}
                    </span>
                )}
                {hasPendingInvites && (
                    <PendingInviteDot className={isLayoutNavCollapsed ? 'absolute top-0.5 right-0.5' : 'mr-0.5'} />
                )}
                {!isLayoutNavCollapsed && !isAiFirst && <MenuOpenIndicator />}
            </ButtonPrimitive>

            <ProjectModal />
            <OrgModal />
        </>
    )
}
