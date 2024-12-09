import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { featureManagementLogic } from './featureManagementLogic'

export function FeatureManagementList(): JSX.Element {
    const { activeFeatureId, features } = useValues(featureManagementLogic)
    const { setActiveFeatureId } = useActions(featureManagementLogic)

    return (
        <ul>
            {features.results.map((feature) => (
                <li key={feature.id}>
                    <LemonButton
                        onClick={() => setActiveFeatureId(feature.id)}
                        size="small"
                        fullWidth
                        active={activeFeatureId === feature.id}
                    >
                        <span className="truncate">{feature.name}</span>
                    </LemonButton>
                </li>
            ))}
        </ul>
    )
}
