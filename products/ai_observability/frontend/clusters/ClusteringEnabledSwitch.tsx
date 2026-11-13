import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { clusteringConfigLogic } from './clusteringConfigLogic'

export function ClusteringEnabledSwitch(): JSX.Element {
    const { config, configLoading, dataProcessingAccepted, dataProcessingApprovalDisabledReason } =
        useValues(clusteringConfigLogic)
    const { setEnabled } = useActions(clusteringConfigLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.AiObservabilityClusters}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <LemonSwitch
                checked={config.enabled}
                onChange={setEnabled}
                loading={configLoading}
                disabledReason={
                    !config.enabled && !dataProcessingAccepted ? dataProcessingApprovalDisabledReason : undefined
                }
                label={config.enabled ? 'Clustering enabled' : 'Clustering disabled'}
                tooltip="Clustering runs automatically. Turning this off stops future runs and keeps existing results."
                data-attr="clusters-enabled-switch"
            />
        </AccessControlAction>
    )
}
