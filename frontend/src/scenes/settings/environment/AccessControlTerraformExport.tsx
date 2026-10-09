import { useValues } from 'kea'
import { Suspense, useState } from 'react'

import { IconCode2 } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { DashboardModalLoading } from 'scenes/dashboard/DashboardModalLoading'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AvailableFeature } from '~/types'

// Loaded on demand like the dashboard export, so the exporters stay out of the settings bundle
const TerraformExportModal = lazyWithRetry(() =>
    import('lib/components/TerraformExporter/TerraformExportModal').then((m) => ({ default: m.TerraformExportModal }))
)

/** The "Manage with Terraform" button on the access control settings page, and the export modal it opens */
export function AccessControlTerraformExport(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [modalOpen, setModalOpen] = useState(false)
    const shouldRenderModal = useKeepMountedWhileOpen(modalOpen)

    if (!currentTeam || !currentOrganization) {
        return null
    }

    return (
        <>
            <LemonButton
                type="tertiary"
                size="small"
                className="group/terraform-button"
                icon={<IconCode2 className="text-secondary group-hover/terraform-button:text-primary" />}
                onClick={() => guardAvailableFeature(AvailableFeature.ACCESS_CONTROL, () => setModalOpen(true))}
                data-attr="access-control-manage-terraform"
            >
                <span className="font-normal text-secondary group-hover/terraform-button:text-primary">
                    Manage with Terraform
                </span>
            </LemonButton>
            {shouldRenderModal ? (
                <Suspense fallback={<DashboardModalLoading isOpen={modalOpen} onClose={() => setModalOpen(false)} />}>
                    <TerraformExportModal
                        isOpen={modalOpen}
                        onClose={() => setModalOpen(false)}
                        resource={{
                            type: 'access_control',
                            data: {
                                projectId: currentTeam.id,
                                projectName: currentTeam.name,
                                organizationId: currentOrganization.id,
                            },
                        }}
                        data-attr="access-control-terraform-modal"
                    />
                </Suspense>
            ) : null}
        </>
    )
}
