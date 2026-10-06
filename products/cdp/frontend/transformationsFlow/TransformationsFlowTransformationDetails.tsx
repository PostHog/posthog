import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import { hogFunctionConfigurationLogic } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { transformationsFlowLogic } from './transformationsFlowLogic'

const CONFIGURATION_LOGIC_KEY = 'transformations-flow'

export function TransformationsFlowTransformationDetails({
    hogFunction,
    position,
}: {
    hogFunction: HogFunctionType
    position: number
}): JSX.Element {
    const { orderedTransformations, transformationsLoading } = useValues(transformationsFlowLogic)
    const { moveTransformation, syncTransformation } = useActions(transformationsFlowLogic)
    const { hogFunction: savedHogFunction } = useValues(
        hogFunctionConfigurationLogic({ id: hogFunction.id, logicKey: CONFIGURATION_LOGIC_KEY })
    )

    // The configuration form saves through its own logic. Copy each saved version into the flow,
    // so that the canvas shows a new name or a disabled transformation without a page reload.
    useEffect(() => {
        if (savedHogFunction) {
            syncTransformation({ hogFunction: savedHogFunction })
        }
    }, [savedHogFunction, syncTransformation])

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    loading={transformationsLoading}
                    disabledReason={position === 1 ? 'This transformation already runs first' : undefined}
                    onClick={() => moveTransformation({ id: hogFunction.id, offset: -1 })}
                    data-attr="transformations-flow-move-earlier"
                >
                    Move earlier
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    loading={transformationsLoading}
                    disabledReason={
                        position === orderedTransformations.length ? 'This transformation already runs last' : undefined
                    }
                    onClick={() => moveTransformation({ id: hogFunction.id, offset: 1 })}
                    data-attr="transformations-flow-move-later"
                >
                    Move later
                </LemonButton>
                <LemonButton size="small" type="tertiary" to={urls.hogFunction(hogFunction.id)}>
                    Open full page
                </LemonButton>
            </div>
            <HogFunctionConfiguration id={hogFunction.id} logicKey={CONFIGURATION_LOGIC_KEY} />
        </div>
    )
}
