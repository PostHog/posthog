import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'

import { HogFunctionFiltersType, HogFunctionSubTemplateIdType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    filters: HogFunctionFiltersType
    subTemplateId?: HogFunctionSubTemplateIdType
    newDisabledReason?: string
}

export function LinkedHogFunctions({
    filters,
    subTemplateId,
    newDisabledReason,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            forceFilters={{ filters, subTemplateId }}
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
