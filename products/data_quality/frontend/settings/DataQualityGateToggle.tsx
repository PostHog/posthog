import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'
import { Field, FieldLabel, Switch } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dataQualityGateLogic } from '../dataQualityGateLogic'

export function DataQualityGateToggle(): JSX.Element | null {
    const { gateConfig, gateReadable, gateSaving } = useValues(dataQualityGateLogic)
    const { setGateEnabled } = useActions(dataQualityGateLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    if (!gateReadable || !gateConfig) {
        return null
    }

    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.WarehouseObjects,
        AccessControlLevel.Editor
    )

    if (todayRailNav) {
        return (
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    checked={gateConfig.gate_materialization_on_checks}
                    onCheckedChange={setGateEnabled}
                    disabled={gateSaving}
                    disabledReason={disabledReason}
                    data-attr="data-quality-gate-toggle"
                />
                <FieldLabel htmlFor={switchId}>Block materialization on failing checks</FieldLabel>
            </Field>
        )
    }

    return (
        <LemonSwitch
            bordered
            checked={gateConfig.gate_materialization_on_checks}
            onChange={setGateEnabled}
            loading={gateSaving}
            disabledReason={disabledReason}
            label="Block materialization on failing checks"
            data-attr="data-quality-gate-toggle"
        />
    )
}
