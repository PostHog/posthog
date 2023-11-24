import { ActionAttribute } from '~/toolbar/actions/ActionAttribute'
import { ActionStepType } from '~/types'

interface ActionStepProps {
    actionStep: ActionStepType
}

type ActionStepPropertyKey = 'text' | 'name' | 'href' | 'selector'

export function ActionStep({ actionStep }: ActionStepProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {(['text', 'name', 'href', 'selector'] as ActionStepPropertyKey[]).map((attr) =>
                actionStep[attr] || attr === 'selector' ? (
                    <ActionAttribute key={attr} attribute={attr} value={actionStep[attr] || undefined} />
                ) : null
            )}
        </div>
    )
}
