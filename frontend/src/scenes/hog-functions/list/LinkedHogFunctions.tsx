import { useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import {
    CyclotronJobFiltersType,
    HogFunctionSubTemplateIdType,
    HogFunctionSubTemplateType,
    HogFunctionTypeType,
} from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from '../sub-templates/sub-templates'
import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    type: HogFunctionTypeType
    forceFilterGroups?: CyclotronJobFiltersType[]
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    newDisabledReason?: string
    hideFeedback?: boolean
    emptyText?: string
    queryParams?: Record<string, string>
}

// A sub-template can widen the filters its trigger shares with the other destinations. A PagerDuty
// alert also runs on the resolved event, so the incident it opened closes again. Its own filters
// therefore win over the common ones, which carry the trigger event alone.
export const getFiltersFromSubTemplateId = (
    subTemplateId: HogFunctionSubTemplateIdType,
    subTemplate?: HogFunctionSubTemplateType | null
): CyclotronJobFiltersType | undefined => {
    const commonProperties = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
    return subTemplate?.filters ?? commonProperties.filters ?? undefined
}

export function LinkedHogFunctions({
    type,
    forceFilterGroups,
    subTemplateIds,
    newDisabledReason,
    hideFeedback,
    emptyText,
    queryParams,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)
    const logicKey = useMemo(() => {
        return JSON.stringify({ type, subTemplateIds, forceFilterGroups })
    }, [type, subTemplateIds, forceFilterGroups])

    // TRICKY: All templates are destinations - internal destinations are just a different source
    // and set by the subtemplate modifier
    const templateType = type === 'internal_destination' ? 'destination' : type

    const getConfigurationOverrides = (
        subTemplateId: HogFunctionSubTemplateIdType | undefined
    ): { filters: CyclotronJobFiltersType } | undefined => {
        if (forceFilterGroups && forceFilterGroups.length > 0) {
            return { filters: forceFilterGroups[0] }
        }
        if (subTemplateId) {
            const filters = getFiltersFromSubTemplateId(subTemplateId)
            return filters ? { filters } : undefined
        }
        return undefined
    }

    const hogFunctionFilterList =
        forceFilterGroups ??
        (subTemplateIds?.map((id) => getFiltersFromSubTemplateId(id)).filter((filters) => !!filters) as
            | CyclotronJobFiltersType[]
            | undefined)

    return showNewDestination ? (
        <HogFunctionTemplateList
            type={templateType}
            subTemplateIds={subTemplateIds}
            getConfigurationOverrides={getConfigurationOverrides}
            queryParams={queryParams}
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
            forceFilterGroups={hogFunctionFilterList}
            type={type}
            returnTo={queryParams?.returnTo}
            hideFeedback={hideFeedback}
            emptyText={emptyText}
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
