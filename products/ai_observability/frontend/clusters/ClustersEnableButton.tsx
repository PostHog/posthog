import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { clusteringConfigLogic } from './clusteringConfigLogic'

export function ClustersEnableButton(): JSX.Element | null {
    const { config, configLoading, dataProcessingAccepted, dataProcessingApprovalDisabledReason } =
        useValues(clusteringConfigLogic)
    const { setEnabled } = useActions(clusteringConfigLogic)

    if (config.enabled) {
        return null
    }
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.AiObservabilityClusters}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonButton
                type="primary"
                className="self-start"
                loading={configLoading}
                disabledReason={!dataProcessingAccepted ? dataProcessingApprovalDisabledReason : undefined}
                data-attr="clusters-enable"
                onClick={() => setEnabled(true)}
            >
                Enable clustering
            </LemonButton>
        </AccessControlAction>
    )
}
