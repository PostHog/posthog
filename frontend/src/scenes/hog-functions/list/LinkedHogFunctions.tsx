import { useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from '../sub-templates/sub-templates'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'
import { HogFunctionList } from './HogFunctionsList'

export type LinkedHogFunctionsProps = {
    type: HogFunctionTypeType
    forceFilterGroups?: CyclotronJobFiltersType[]
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    newDisabledReason?: string
    hideFeedback?: boolean
    emptyText?: string
}

const getFiltersFromSubTemplateId = (
    subTemplateId: HogFunctionSubTemplateIdType
): CyclotronJobFiltersType | undefined => {
    const commonProperties = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
    return commonProperties.filters ?? undefined
}

export function LinkedHogFunctions({
    type,
    forceFilterGroups,
    subTemplateIds,
    newDisabledReason,
    hideFeedback,
    emptyText,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)
    const logicKey = useMemo(() => {
        return JSON.stringify({ type, subTemplateIds, forceFilterGroups })
    }, [type, subTemplateIds, forceFilterGroups])

    // TRICKY: All templates are destinations - internal destinations are just a different source
    // and set by the subtemplate modifier
    const templateType = type === 'internal_destination' ? 'destination' : type

    const getConfigurationOverrides = (
        subTemplateId?: HogFunctionSubTemplateIdType
    ): CyclotronJobFiltersType | undefined => {
        if (forceFilterGroups && forceFilterGroups.length > 0) {
            return forceFilterGroups[0]
        }
        if (subTemplateId) {
            return getFiltersFromSubTemplateId(subTemplateId)
        }
        return undefined
    }

    const hogFunctionFilterList =
        forceFilterGroups ??
        (subTemplateIds?.map(getFiltersFromSubTemplateId).filter((filters) => !!filters) as
            | CyclotronJobFiltersType[]
            | undefined)

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
            forceFilterGroups={hogFunctionFilterList}
            type={type}
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
