import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { clusteringConfigLogic } from './clusteringConfigLogic'
import { ClusteringEnabledSwitch } from './ClusteringEnabledSwitch'
import { ClusteringJobsButton } from './ClusteringJobsButton'

export function ClustersSetupActions(): JSX.Element {
    const { config, configLoading, dataProcessingAccepted, dataProcessingApprovalDisabledReason } =
        useValues(clusteringConfigLogic)
    const { setEnabled } = useActions(clusteringConfigLogic)

    if (config.enabled) {
        return (
            <div className="flex items-center gap-4 flex-wrap">
                <ClusteringJobsButton />
                <ClusteringEnabledSwitch />
            </div>
        )
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
