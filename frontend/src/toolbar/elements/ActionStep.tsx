import { ActionAttribute } from '~/toolbar/elements/ActionAttribute'
import { ActionStepType, ElementType } from '~/types'

interface ActionStepProps {
    actionStep: ActionStepType
    activeElementChain: ElementType[]
    overriddenSelector?: string
}

type ActionStepPropertyKey = 'text' | 'name' | 'href' | 'selector'

export function ActionStep({ actionStep, activeElementChain, overriddenSelector }: ActionStepProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            {(['text', 'name', 'href', 'selector'] as ActionStepPropertyKey[]).map((attr) => {
                return actionStep[attr] || attr === 'selector' ? (
                    <ActionAttribute
                        key={attr}
                        attribute={attr}
                        value={
                            attr === 'selector'
                                ? overriddenSelector || actionStep[attr] || undefined
                                : actionStep[attr] || undefined
                        }
                        activeElementChain={activeElementChain}
                    />
                ) : null
            })}
        </div>
    )
}
