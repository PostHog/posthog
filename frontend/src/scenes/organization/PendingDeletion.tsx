import { useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { SupportModalButton } from 'scenes/authentication/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: OrganizationPendingDeletion,
    logic: organizationLogic,
}

export function OrganizationPendingDeletion(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const hasOtherOrgs = otherOrganizations.length > 0

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HogWelder className="h-80" />
                    <h3>
                        Disassembling {currentOrganization?.name ? `"${currentOrganization.name}"` : 'all'} data at the
                        circuit level
                    </h3>
                    <p className="text-secondary">
                        Our hedgehog engineer is carefully taking everything apart. Your organization will be completely
                        deleted shortly - this usually takes a couple of minutes.
                    </p>
                    {hasOtherOrgs && (
                        <>
                            <p className="text-secondary text-sm">Switch to another organization:</p>
                            <div className="w-full max-w-[400px] border rounded overflow-hidden">
                                <OrgSwitcher dialog={false} />
                            </div>
                        </>
                    )}
                    <SupportModalButton kind="support" target_area="billing" label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
