import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useState } from 'react'

import { AvailableFeature, HogFunctionFiltersType, HogFunctionSubTemplateIdType, HogFunctionTypeType } from '~/types'

import { hogFunctionListLogic } from './hogFunctionListLogic'
import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    logicKey?: string
    type: HogFunctionTypeType
    filters: HogFunctionFiltersType
    subTemplateId?: HogFunctionSubTemplateIdType
    newDisabledReason?: string
    feature?: AvailableFeature
}

export function LinkedHogFunctions({
    logicKey,
    type,
    filters,
    subTemplateId,
    newDisabledReason,
    feature,
}: LinkedHogFunctionsProps): JSX.Element | null {
    const logicProps = { logicKey, forceFilters: { filters }, type }

    const { hogFunctions } = useValues(hogFunctionListLogic(logicProps))
    const [showNewDestination, setShowNewDestination] = useState(false)

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            type={type}
            subTemplateId={subTemplateId}
            forceFilters={{ filters }}
            feature={feature}
            currentUsage={hogFunctions.length}
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
            {...logicProps}
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
