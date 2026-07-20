import { useActions, useMountedLogic, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { ProjectSwitcher } from 'lib/components/Account/ProjectSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { projectLogic } from 'scenes/projectLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { pendingDeletionLogic } from './pendingDeletionLogic'

export const scene: SceneExport = {
    component: ProjectPendingDeletion,
    logic: projectLogic,
}

export function ProjectPendingDeletion(): JSX.Element {
    // Mount the poller so the screen reacts on its own when deletion finishes or the lock is cleared.
    useMountedLogic(pendingDeletionLogic)
    const { currentProject } = useValues(projectLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { isProjectSwitcherOpen, isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openProjectSwitcher, closeProjectSwitcher, openOrgSwitcher, closeOrgSwitcher } =
        useActions(newAccountMenuLogic)
    const hasOtherOrgs = otherOrganizations.length > 0

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HogWelder className="h-80" />
                    <h3>
                        Disassembling {currentProject?.name ? `"${currentProject.name}"` : 'this project'} at the
                        circuit level
                    </h3>
                    <p className="text-secondary">
                        Our hedgehog engineer is carefully taking everything apart. This runs in the background, so it's
                        safe to close this page. Projects with a lot of data can take several hours, sometimes
                        overnight. We'll email you when it's done.
                    </p>
                    <div className="flex items-center gap-2 text-secondary text-sm">
                        <Spinner />
                        <span>
                            {currentProject?.updated_at
                                ? `Deletion started ${dayjs(currentProject.updated_at).fromNow()}`
                                : 'Deletion in progress'}
                        </span>
                    </div>
                    <p className="text-muted text-xs">
                        Still here after a day or more? That's unusual. Contact support and we'll take a look.
                    </p>
                    <div className="flex items-center gap-2">
                        <Popover
                            visible={isProjectSwitcherOpen}
                            onClickOutside={closeProjectSwitcher}
                            overlay={
                                <div className="w-[320px]">
                                    <ProjectSwitcher dialog={false} />
                                </div>
                            }
                            placement="bottom"
                        >
                            <LemonButton
                                type="primary"
                                onClick={() => (isProjectSwitcherOpen ? closeProjectSwitcher() : openProjectSwitcher())}
                                sideIcon={<IconChevronDown />}
                            >
                                Switch project
                            </LemonButton>
                        </Popover>
                        {hasOtherOrgs && (
                            <Popover
                                visible={isOrgSwitcherOpen}
                                onClickOutside={closeOrgSwitcher}
                                overlay={
                                    <div className="w-[320px]">
                                        <OrgSwitcher dialog={false} />
                                    </div>
                                }
                                placement="bottom"
                            >
                                <LemonButton
                                    type="secondary"
                                    onClick={() => (isOrgSwitcherOpen ? closeOrgSwitcher() : openOrgSwitcher())}
                                    sideIcon={<IconChevronDown />}
                                >
                                    Switch organization
                                </LemonButton>
                            </Popover>
                        )}
                    </div>
                    <SupportModalButton kind="support" target_area="login" label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
