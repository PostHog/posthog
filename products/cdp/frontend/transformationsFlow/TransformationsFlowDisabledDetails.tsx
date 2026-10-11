import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { HogFunctionType } from '~/types'

import { transformationsFlowLogic } from './transformationsFlowLogic'

export function TransformationsFlowDisabledDetails({ hogFunction }: { hogFunction: HogFunctionType }): JSX.Element {
    const { transformationsLoading } = useValues(transformationsFlowLogic)
    const { setTransformationEnabled } = useActions(transformationsFlowLogic)

    return (
        <div className="flex flex-col gap-2 items-start">
            <p className="m-0">This transformation is disabled. Events do not go through it.</p>
            <p className="m-0">
                When you enable it, it runs after your other transformations. You can then move it to a different
                position.
            </p>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    size="small"
                    type="primary"
                    loading={transformationsLoading}
                    onClick={() => setTransformationEnabled({ hogFunction, enabled: true })}
                    data-attr="transformations-flow-enable"
                >
                    Enable and add to the end
                </LemonButton>
                <LemonButton size="small" type="tertiary" to={urls.hogFunction(hogFunction.id)}>
                    Open full page
                </LemonButton>
            </div>
        </div>
    )
}
