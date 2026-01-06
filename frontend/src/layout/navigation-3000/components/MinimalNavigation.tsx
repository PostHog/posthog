import { useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { ProjectMenu } from 'lib/components/Account/ProjectMenu'
import { organizationLogic } from 'scenes/organizationLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigation3000Logic } from '../navigationLogic'
import { ZenModeButton } from './ZenModeButton'

export function MinimalNavigation(): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { hasOnboardedAnyProduct, currentTeam } = useValues(teamLogic)
    const { zenMode } = useValues(navigation3000Logic)
    const { titleAndIcon } = useValues(sceneLogic)

    const shouldShowOnboarding = !hasOnboardedAnyProduct && !currentTeam?.ingested_event
    const logoUrl = shouldShowOnboarding ? urls.useCaseSelection() : urls.projectRoot()

    return (
        <nav className="flex items-center gap-2 p-2 border-b">
            <LemonButton noPadding icon={<IconLogomark className="text-3xl mx-2" />} to={logoUrl} />
            {zenMode && (
                <div className="flex-1 flex justify-start items-center px-4">
                    <span className="text-lg font-semibold text-primary truncate">{titleAndIcon.title}</span>
                </div>
            )}
            <div className={`flex items-center justify-end gap-2 ${zenMode ? '' : 'flex-1'}`}>
                <ZenModeButton />
                {(currentOrganization?.teams?.length ?? 0 > 1) ? (
                    <ProjectMenu
                        buttonProps={{
                            size: 'lg',
                            className: 'h-[37px]', // Match the height of the `AccountPopoverOverlay`, remove when we redo the account
                        }}
                    />
                ) : null}
                <AccountMenu
                    align="end"
                    side="bottom"
                    alignOffset={10}
                    trigger={
                        <LemonButton type="tertiary" icon={<ProfilePicture user={user} size="md" />}>
                            {user?.first_name || user?.email}
                        </LemonButton>
                    }
                />
            </div>
        </nav>
    )
}
