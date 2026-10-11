import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel } from '@posthog/lemon-ui'

import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { transformationsFlowLogic } from './transformationsFlowLogic'

export function TransformationsFlowOverview(): JSX.Element {
    const { orderedTransformations, disabledTransformations, transformationsLoading } =
        useValues(transformationsFlowLogic)
    const { setTransformationEnabled, selectStep } = useActions(transformationsFlowLogic)

    return (
        <div className="flex flex-col gap-3">
            <p className="m-0">
                PostHog sends each event through these steps, from top to bottom. Your enabled transformations run in
                the order shown. Each transformation gets the event that the step before it returns.
            </p>
            <p className="m-0">Select a step to see what it does, or to change a transformation.</p>
            {orderedTransformations.length === 0 && (
                <div className="flex flex-col gap-2 items-start">
                    <p className="m-0">
                        You have no enabled transformations. Events go from capture to storage unchanged.
                    </p>
                    <LemonButton size="small" type="primary" onClick={() => selectStep('add')}>
                        Add a transformation
                    </LemonButton>
                </div>
            )}
            {disabledTransformations.length > 0 && (
                <div className="flex flex-col gap-2">
                    <LemonLabel info="Events do not go through disabled transformations. When you enable one, it runs after your other transformations.">
                        Disabled transformations
                    </LemonLabel>
                    {disabledTransformations.map((hogFunction) => (
                        <div key={hogFunction.id} className="flex items-center gap-2 min-w-0">
                            <HogFunctionIcon src={hogFunction.icon_url} size="small" />
                            <span className="flex-1 min-w-0 truncate">{hogFunction.name}</span>
                            <LemonButton
                                size="small"
                                type="secondary"
                                loading={transformationsLoading}
                                onClick={() => setTransformationEnabled({ hogFunction, enabled: true })}
                                data-attr="transformations-flow-overview-enable"
                            >
                                Enable and add to the end
                            </LemonButton>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
