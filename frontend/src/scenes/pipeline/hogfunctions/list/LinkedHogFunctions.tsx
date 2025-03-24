import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'

import { HogFunctionFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    logicKey?: string
    type: HogFunctionTypeType
    filters: HogFunctionFiltersType
    subTemplateId?: HogFunctionSubTemplateIdType
    newDisabledReason?: string
}

export function LinkedHogFunctions({
    logicKey,
    type,
    filters,
    subTemplateId,
    newDisabledReason,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const [showNewDestination, setShowNewDestination] = useState(false)

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            type={type}
            subTemplateId={subTemplateId}
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
            logicKey={logicKey}
            forceFilters={{ filters }}
            type={type}
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
