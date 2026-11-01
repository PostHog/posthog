import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { AI_CREDIT_PRESET_AMOUNTS_USD, aiCreditsLogic, MINIMUM_AI_CREDIT_USD } from './aiCreditsLogic'

const OTHER_AMOUNT = 'other'

export function AmountChoices({ error }: { error?: string }): JSX.Element {
    const { addFundsForm } = useValues(aiCreditsLogic)
    const { setAddFundsFormValues } = useActions(aiCreditsLogic)

    const chosen =
        !addFundsForm.customAmount && AI_CREDIT_PRESET_AMOUNTS_USD.includes(addFundsForm.amountUsd ?? 0)
            ? String(addFundsForm.amountUsd)
            : OTHER_AMOUNT

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2" role="group" aria-label="Amount" data-attr="ai-credits-amount">
                {[...AI_CREDIT_PRESET_AMOUNTS_USD.map(String), OTHER_AMOUNT].map((choice) => (
                    <button
                        key={choice}
                        type="button"
                        aria-pressed={choice === chosen}
                        onClick={() =>
                            setAddFundsFormValues(
                                choice === OTHER_AMOUNT
                                    ? { customAmount: true }
                                    : { customAmount: false, amountUsd: Number(choice) }
                            )
                        }
                        className={cn(
                            'h-11 flex-1 cursor-pointer rounded text-base',
                            choice === chosen
                                ? 'border-2 border-accent bg-accent-highlight-secondary'
                                : 'border bg-surface-primary hover:bg-fill-highlight-100',
                            choice === OTHER_AMOUNT ? 'font-medium text-secondary' : 'font-semibold'
                        )}
                    >
                        {choice === OTHER_AMOUNT ? 'Other' : humanFriendlyCurrency(choice, 0)}
                    </button>
                ))}
            </div>
            {chosen === OTHER_AMOUNT && (
                <LemonInput
                    type="number"
                    prefix={<span>$</span>}
                    min={MINIMUM_AI_CREDIT_USD}
                    value={addFundsForm.amountUsd ?? undefined}
                    onChange={(amountUsd) => setAddFundsFormValues({ amountUsd })}
                    status={error ? 'danger' : 'default'}
                    autoFocus
                    data-attr="ai-credits-custom-amount"
                />
            )}
        </div>
    )
}
