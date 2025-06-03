import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'

import { HogFunctionFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    type: HogFunctionTypeType
    filters: HogFunctionFiltersType
    subTemplateIds?: HogFunctionSubTemplateIdType[]
    newDisabledReason?: string
    hideFeedback?: boolean
}

export function LinkedHogFunctions({
    type,
    filters,
    subTemplateIds,
    newDisabledReason,
    hideFeedback,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)

    // TRICKY: All templates are destinations - internal destinations are just a different source
    // and set by the subtemplate modifier

    const templateType = type === 'internal_destination' ? 'destination' : type

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            type={templateType}
            subTemplateIds={subTemplateIds}
            forceFilters={{ filters }}
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
            forceFilters={{ filters }}
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
