import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { ProjectSwitcher } from 'lib/components/Account/ProjectSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { projectLogic } from 'scenes/projectLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: ProjectPendingDeletion,
    logic: projectLogic,
}

export function ProjectPendingDeletion(): JSX.Element {
    const { currentProject, cancelProjectDeletionLoading } = useValues(projectLogic)
    const { cancelProjectDeletion } = useActions(projectLogic)
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
                        This project is scheduled for deletion
                        <strong>
                            {currentProject?.deletion_scheduled_at
                                ? ` on ${dayjs(currentProject.deletion_scheduled_at).format('MMMM D, YYYY [at] h:mm A')}`
                                : ' soon'}
                        </strong>
                        . If you've changed you mind, you can cancel project deletion before then.
                    </p>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => cancelProjectDeletion()}
                            loading={cancelProjectDeletionLoading}
                            data-attr="cancel-project-deletion"
                        >
                            Cancel project deletion
                        </LemonButton>
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
                    <SupportModalButton kind="support" label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
