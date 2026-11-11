import { useValues } from 'kea'
import { useState } from 'react'

import { IconCode2 } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AvailableFeature } from '~/types'

/** The "Manage with Terraform" button on the access control settings page, and the export modal it opens */
export function AccessControlTerraformExport(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [modalOpen, setModalOpen] = useState(false)

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
        </>
    )
}
