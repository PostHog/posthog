import { useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { buildAlertFilterConfig } from 'lib/utils'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from '../sub-templates/sub-templates'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'
import { HogFunctionList } from './HogFunctionsList'

type LinkedHogFunctionsBaseProps = {
    type: HogFunctionTypeType
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    newDisabledReason?: string
    hideFeedback?: boolean
}

export type LinkedHogFunctionsProps = LinkedHogFunctionsBaseProps &
    (
        | { alertId: string; forceFilterGroups?: never }
        | { alertId?: never; forceFilterGroups?: CyclotronJobFiltersType[] }
    )

const getFiltersFromSubTemplateId = (
    subTemplateId: HogFunctionSubTemplateIdType
): CyclotronJobFiltersType | undefined => {
    const commonProperties = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
    return commonProperties.filters ?? undefined
}

export function LinkedHogFunctions({
    type,
    forceFilterGroups,
    alertId,
    subTemplateIds,
    newDisabledReason,
    hideFeedback,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)
    const logicKey = useMemo(() => {
        return JSON.stringify({ type, subTemplateIds, forceFilterGroups, alertId })
    }, [type, subTemplateIds, forceFilterGroups, alertId])

    // TRICKY: All templates are destinations - internal destinations are just a different source
    // and set by the subtemplate modifier
    const templateType = type === 'internal_destination' ? 'destination' : type

    const getConfigurationOverrides = (
        subTemplateId?: HogFunctionSubTemplateIdType
    ): CyclotronJobFiltersType | undefined => {
        if (alertId) {
            return buildAlertFilterConfig(alertId)
        }
        if (forceFilterGroups && forceFilterGroups.length > 0) {
            return forceFilterGroups[0]
        }
        if (subTemplateId) {
            return getFiltersFromSubTemplateId(subTemplateId)
        }
        return undefined
    }

    // Only compute filter list when not using alertId (alertId provides filters via buildAlertFilterConfig)
    const hogFunctionFilterList = alertId
        ? undefined
        : (forceFilterGroups ??
          (subTemplateIds?.map(getFiltersFromSubTemplateId).filter((filters) => !!filters) as
              | CyclotronJobFiltersType[]
              | undefined))

    return showNewDestination ? (
        <HogFunctionTemplateList
            type={templateType}
            subTemplateIds={subTemplateIds}
            getConfigurationOverrides={getConfigurationOverrides}
            extraControls={
                <>
                    <LemonButton type="secondary" size="small" onClick={() => setShowNewDestination(false)}>
                        Cancel
                    </LemonButton>
                </>
            }
        />
    ) : (
        <HogFunctionList
            key={logicKey}
            type={type}
            hideFeedback={hideFeedback}
            {...(alertId ? { alertId } : { forceFilterGroups: hogFunctionFilterList })}
            extraControls={
                <>
                    <LemonButton
                        type="primary"
                        size="small"
                        disabledReason={newDisabledReason}
                        onClick={() => setShowNewDestination(true)}
                    >
                        New notification
                    </LemonButton>
                </>
            }
        />
    )
}
