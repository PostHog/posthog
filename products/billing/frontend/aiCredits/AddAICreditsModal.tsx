import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyCurrency } from 'lib/utils/numbers'

import { AI_CREDIT_PRESET_AMOUNTS_USD, aiCreditsLogic, automaticReloadConsent, cardLabel } from './aiCreditsLogic'
import { ReloadAmountFields } from './ReloadAmountFields'

const OTHER_AMOUNT = 'other'

export function AddAICreditsModal(): JSX.Element {
    const {
        addFundsModalOpen,
        addFundsForm,
        isAddFundsFormSubmitting,
        quote,
        quoteLoading,
        quoteError,
        purchaseError,
        card,
        cardLoading,
        settings,
    } = useValues(aiCreditsLogic)
    const { closeAddFundsModal, setAddFundsFormValues, submitAddFundsForm } = useActions(aiCreditsLogic)

    const cardOnFile = card?.card ?? null
    const reloadAlreadyOn = settings?.automatic_reload.enabled ?? false
    const amountChoice =
        !addFundsForm.customAmount && AI_CREDIT_PRESET_AMOUNTS_USD.includes(addFundsForm.amountUsd ?? 0)
            ? String(addFundsForm.amountUsd)
            : OTHER_AMOUNT

    return (
        <LemonModal
            isOpen={addFundsModalOpen}
            onClose={closeAddFundsModal}
            title="Add funds"
            description="Buy AI credits with the card on file."
            width={560}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeAddFundsModal}
                        disabledReason={isAddFundsFormSubmitting ? 'The payment is in progress' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitAddFundsForm}
                        loading={isAddFundsFormSubmitting}
                        disabledReason={
                            !cardOnFile
                                ? 'Add a card to your billing details first'
                                : !quote
                                  ? 'Wait for the total'
                                  : undefined
                        }
                        data-attr="ai-credits-pay"
                    >
                        {quote ? `Pay ${humanFriendlyCurrency(quote.total_usd)}` : 'Pay'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={aiCreditsLogic} formKey="addFundsForm" className="flex flex-col gap-4">
                <LemonField name="amountUsd" label="Amount" help="The minimum is $20">
                    {({ error }) => (
                        <div className="flex flex-col gap-2">
                            <LemonSegmentedButton
                                fullWidth
                                value={amountChoice}
                                onChange={(choice) =>
                                    choice === OTHER_AMOUNT
                                        ? setAddFundsFormValues({ customAmount: true })
                                        : setAddFundsFormValues({ customAmount: false, amountUsd: Number(choice) })
                                }
                                options={[
                                    ...AI_CREDIT_PRESET_AMOUNTS_USD.map((amount) => ({
                                        value: String(amount),
                                        label: humanFriendlyCurrency(amount, 0),
                                    })),
                                    { value: OTHER_AMOUNT, label: 'Other' },
                                ]}
                                data-attr="ai-credits-amount"
                            />
                            {amountChoice === OTHER_AMOUNT && (
                                <LemonInput
                                    type="number"
                                    prefix={<span>$</span>}
                                    min={20}
                                    value={addFundsForm.amountUsd ?? undefined}
                                    onChange={(amountUsd) => setAddFundsFormValues({ amountUsd })}
                                    status={error ? 'danger' : 'default'}
                                    autoFocus
                                    data-attr="ai-credits-custom-amount"
                                />
                            )}
                        </div>
                    )}
                </LemonField>

                <div className="flex flex-col gap-1 rounded border bg-surface-secondary p-3">
                    {quoteError ? (
                        <span className="text-danger">{quoteError}</span>
                    ) : quoteLoading || !quote ? (
                        <LemonSkeleton repeat={3} />
                    ) : (
                        <>
                            <div className="flex justify-between">
                                <span>AI credits</span>
                                <span>{humanFriendlyCurrency(quote.amount_usd)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Tax</span>
                                <span>{humanFriendlyCurrency(quote.tax_usd)}</span>
                            </div>
                            <LemonDivider className="my-1" />
                            <div className="flex justify-between font-semibold">
                                <span>Total due today</span>
                                <span>{humanFriendlyCurrency(quote.total_usd)}</span>
                            </div>
                        </>
                    )}
                </div>

                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Card</span>
                    {cardLoading ? (
                        <LemonSkeleton />
                    ) : cardOnFile ? (
                        <span>
                            {cardLabel(cardOnFile)}, expires {String(cardOnFile.exp_month).padStart(2, '0')}/
                            {String(cardOnFile.exp_year).slice(-2)}
                        </span>
                    ) : (
                        <span className="text-secondary">
                            No card on file. Add one in your billing details, then come back.
                        </span>
                    )}
                </div>

                {!reloadAlreadyOn && cardOnFile && (
                    <div className="flex flex-col gap-3 rounded border p-3">
                        <LemonField name="reloadEnabled">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    label="Reload automatically when the balance runs low"
                                    fullWidth
                                    data-attr="ai-credits-add-funds-reload"
                                />
                            )}
                        </LemonField>
                        {addFundsForm.reloadEnabled && (
                            <>
                                <ReloadAmountFields />
                                <p className="m-0 text-xs text-secondary">
                                    {automaticReloadConsent(cardOnFile, addFundsForm)}
                                </p>
                            </>
                        )}
                    </div>
                )}

                {purchaseError && <LemonBanner type="error">{purchaseError}</LemonBanner>}
            </Form>
        </LemonModal>
    )
}
