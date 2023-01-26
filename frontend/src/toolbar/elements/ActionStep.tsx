import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconArrowDown, IconArrowUp } from 'lib/components/icons'
import { ActionAttribute } from '~/toolbar/elements/ActionAttribute'
import { ActionStepType } from '~/types'
import { elementsLogic } from './elementsLogic'

interface ActionStepProps {
    actionStep: ActionStepType
}

type ActionStepPropertyKey = 'text' | 'name' | 'href' | 'selector'

export function ActionStep({ actionStep }: ActionStepProps): JSX.Element {
    const { incrementDesiredSelectorsLength, decrementDesiredSelectorsLength } = useActions(elementsLogic)
    const { canDecrementSelectorsLength } = useValues(elementsLogic)
    return (
        <div>
            {(['text', 'name', 'href', 'selector'] as ActionStepPropertyKey[]).map((attr) => {
                return (
                    <div className="flex flex-row gap-2" key={attr}>
                        {actionStep[attr] || attr === 'selector' ? (
                            <ActionAttribute attribute={attr} value={actionStep[attr] || undefined} />
                        ) : null}
                        {attr === 'selector' ? (
                            <>
                                <div className="flex flex-col gap-2">
                                    <LemonButton
                                        type="primary"
                                        onClick={incrementDesiredSelectorsLength}
                                        icon={<IconArrowUp />}
                                        size="small"
                                        aria-label="increment desired selectors length"
                                    />
                                    <LemonButton
                                        type="primary"
                                        onClick={decrementDesiredSelectorsLength}
                                        icon={<IconArrowDown />}
                                        size="small"
                                        aria-label="decrement desired selectors length"
                                        disabledReason={
                                            canDecrementSelectorsLength
                                                ? undefined
                                                : 'Cannot look for fewer than 1 selector'
                                        }
                                    />
                                </div>
                            </>
                        ) : null}
                    </div>
                )
            })}
        </div>
    )
}
