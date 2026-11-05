import { useValues } from 'kea'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { accessControlsLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/accessControlsLogic'
import { ObjectAccessRules } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/ObjectAccessRules'
import { AvailableFeature } from '~/types'

export function TeamObjectAccessControl({ projectId }: { projectId: string }): JSX.Element {
    const { defaults, terraformDisabledReason } = useValues(accessControlsLogic({ projectId }))

    return (
        <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="resource-access-control-default-settings">
            <ObjectAccessRules
                projectId={projectId}
                scopeType="default"
                subjectId="default"
                subjectNoun="project"
                canEdit={defaults?.can_edit ?? false}
                cannotEditReason={terraformDisabledReason}
            />
        </PayGateMini>
    )
}
