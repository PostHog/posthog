import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dataQualityGateLogic } from '../dataQualityGateLogic'

export function DataQualityGateToggle(): JSX.Element | null {
    const { gateConfig, gateReadable, gateSaving } = useValues(dataQualityGateLogic)
    const { setGateEnabled } = useActions(dataQualityGateLogic)

    if (!gateReadable || !gateConfig) {
        return null
    }

    return (
        <LemonSwitch
            bordered
            checked={gateConfig.gate_materialization_on_checks}
            onChange={setGateEnabled}
            loading={gateSaving}
            disabledReason={getAccessControlDisabledReason(
                AccessControlResourceType.WarehouseObjects,
                AccessControlLevel.Editor
            )}
            label="Block materialization on failing checks"
            tooltip="Applies to all materialized views in this project. When an error-severity check fails, the previous version keeps serving."
            data-attr="data-quality-gate-toggle"
        />
    )
}
