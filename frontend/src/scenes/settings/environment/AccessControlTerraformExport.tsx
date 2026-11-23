import { useValues } from 'kea'
import { useState } from 'react'

import { IconCode2 } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { QuillTerraformExportModal } from 'lib/components/TerraformExporter/QuillTerraformExportModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AvailableFeature } from '~/types'

/** The "Manage with Terraform" button on the access control settings page, and the export modal it opens */
export function AccessControlTerraformExport(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [modalOpen, setModalOpen] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!currentTeam || !currentOrganization) {
        return null
    }

    const openModal = (): void => {
        guardAvailableFeature(AvailableFeature.ACCESS_CONTROL, () => setModalOpen(true))
    }

    const resource = {
        type: 'access_control' as const,
        data: {
            projectId: currentTeam.id,
            projectName: currentTeam.name,
            organizationId: currentOrganization.id,
        },
    }

    return (
        <>
            {todayRailNav ? (
                <Button onClick={openModal} data-attr="access-control-manage-terraform">
                    <IconCode2 />
                    Manage with Terraform
                </Button>
            ) : (
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="group/terraform-button"
                    icon={<IconCode2 className="text-secondary group-hover/terraform-button:text-primary" />}
                    onClick={openModal}
                    data-attr="access-control-manage-terraform"
                >
                    <span className="font-normal text-secondary group-hover/terraform-button:text-primary">
                        Manage with Terraform
                    </span>
                </LemonButton>
            )}
            {todayRailNav ? (
                <QuillTerraformExportModal
                    isOpen={modalOpen}
                    onClose={() => setModalOpen(false)}
                    resource={resource}
                    data-attr="access-control-terraform-modal"
                />
            ) : (
                <TerraformExportModal
                    isOpen={modalOpen}
                    onClose={() => setModalOpen(false)}
                    resource={resource}
                    data-attr="access-control-terraform-modal"
                />
            )}
        </>
    )
}
