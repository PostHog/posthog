import { LemonButton } from '@posthog/lemon-ui'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useState } from 'react'

import { HogFunctionFiltersType, HogFunctionSubTemplateIdType } from '~/types'

import { HogFunctionList } from './HogFunctionsList'
import { HogFunctionTemplateList } from './HogFunctionTemplateList'

export type LinkedHogFunctionsProps = {
    filters: HogFunctionFiltersType
    subTemplateIds?: HogFunctionSubTemplateIdType[]
}

export function LinkedHogFunctions({ filters, subTemplateIds }: LinkedHogFunctionsProps): JSX.Element | null {
    const hogFunctionsEnabled = useFeatureFlag('HOG_FUNCTIONS')
    const [showNewDestination, setShowNewDestination] = useState(false)

    if (!hogFunctionsEnabled) {
        return null
    }

    return showNewDestination ? (
        <HogFunctionTemplateList
            defaultFilters={{}}
            forceFilters={{ filters, subTemplateIds }}
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
            defaultFilters={{ onlyActive: true }}
            forceFilters={{ filters }}
            extraControls={
                <>
                    <LemonButton type="primary" size="small" onClick={() => setShowNewDestination(true)}>
                        New notification
                    </LemonButton>
                </>
            }
        />
    )
}
