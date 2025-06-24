import { LemonButton } from '@posthog/lemon-ui'
import { useMemo, useState } from 'react'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from '../sub-templates/sub-templates'
import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    type: HogFunctionTypeType
    forceFilterGroups?: CyclotronJobFiltersType[]
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    newDisabledReason?: string
    hideFeedback?: boolean
}

const getFiltersFromSubTemplateIds = (subTemplateIds: HogFunctionSubTemplateIdType[]): CyclotronJobFiltersType[] => {
    const filterGroups: CyclotronJobFiltersType[] = []

    for (const subTemplateId of subTemplateIds) {
        const commonProperties = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[subTemplateId]
        if (commonProperties.filters) {
            filterGroups.push(commonProperties.filters)
        }
    }

    return filterGroups
}

export function LinkedHogFunctions({
    type,
    forceFilterGroups,
    subTemplateIds,
    newDisabledReason,
    hideFeedback,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)
    const logicKey = useMemo(() => {
        return JSON.stringify({ type, subTemplateIds, forceFilterGroups })
    }, [type, subTemplateIds, forceFilterGroups])

    // TRICKY: All templates are destinations - internal destinations are just a different source
    // and set by the subtemplate modifier
    const templateType = type === 'internal_destination' ? 'destination' : type

    const filterGroups = forceFilterGroups ?? getFiltersFromSubTemplateIds(subTemplateIds ?? [])

    return showNewDestination ? (
        <HogFunctionTemplateList
            type={templateType}
            subTemplateIds={subTemplateIds}
            configurationOverrides={filterGroups.length ? { filters: filterGroups[0] } : undefined}
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
            forceFilterGroups={filterGroups}
            type={type}
            hideFeedback={hideFeedback}
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
