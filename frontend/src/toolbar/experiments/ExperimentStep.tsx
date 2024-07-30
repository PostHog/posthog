import { ActionAttribute } from '~/toolbar/actions/ActionAttribute'
import { ActionStepType } from '~/types'

interface ExperimentStepProps {
    ExperimentStep: ActionStepType
}

type ExperimentStepPropertyKey = 'text' | 'name' | 'href' | 'selector'

export function ExperimentStep({ ExperimentStep }: ExperimentStepProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {(['text', 'name', 'href', 'selector'] as ExperimentStepPropertyKey[]).map((attr) =>
                ExperimentStep[attr] || attr === 'selector' ? (
                    <ActionAttribute key={attr} attribute={attr} value={ExperimentStep[attr] || undefined} />
                ) : null
            )}
        </div>
    )
}
