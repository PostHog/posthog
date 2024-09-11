import { useValues } from 'kea'

import { ActionAttribute } from '~/toolbar/actions/ActionAttribute'
import { ActionStepType } from '~/types'

import { actionsTabLogic } from './actionsTabLogic'

interface ActionStepProps {
    actionStep: ActionStepType
}

export type ActionStepPropertyKey = 'text' | 'name' | 'href' | 'selector' | 'url'

export function ActionStep({ actionStep }: ActionStepProps): JSX.Element {
    const { automaticActionCreationEnabled } = useValues(actionsTabLogic)

    const stepTypes = ['text', 'name', 'href', 'selector', automaticActionCreationEnabled ? 'url' : null].filter(
        (key) => key
    ) as ActionStepPropertyKey[]

    return (
        <div className="flex flex-col gap-2">
            {stepTypes.map((attr) =>
                actionStep[attr] || attr === 'selector' ? (
                    <ActionAttribute key={attr} attribute={attr} value={actionStep[attr] || undefined} />
                ) : null
            )}
        </div>
    )
}
