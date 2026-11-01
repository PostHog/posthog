import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { organizationLogic } from 'scenes/organizationLogic'

import {
    AI_CREDIT_PRESET_AMOUNTS_USD,
    aiCreditsLogic,
    automaticReloadConsent,
    MINIMUM_AI_CREDIT_USD,
    purchaseConsent,
} from './aiCreditsLogic'
import { CardOnFile } from './CardOnFile'
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
    const { currentOrganization } = useValues(organizationLogic)

    const cardOnFile = card?.card ?? null
    const reloadAlreadyOn = settings?.automatic_reload.enabled ?? false
    const amountChoice =
        !addFundsForm.customAmount && AI_CREDIT_PRESET_AMOUNTS_USD.includes(addFundsForm.amountUsd ?? 0)
            ? String(addFundsForm.amountUsd)
            : OTHER_AMOUNT
    const consent =
        cardOnFile && quote
            ? addFundsForm.reloadEnabled && !reloadAlreadyOn
                ? automaticReloadConsent(cardOnFile, addFundsForm, quote.total_usd)
                : purchaseConsent(cardOnFile, quote.total_usd)
            : null

    return (
        <LemonModal
            isOpen={addFundsModalOpen}
            onClose={closeAddFundsModal}
            title="Add funds"
            description={
                currentOrganization ? (
                    <>
                        For <span className="font-semibold text-primary">{currentOrganization.name}</span>
                    </>
                ) : undefined
            }
            width={560}
            footer={
                <div className="flex w-full flex-col gap-4">
                    {consent && <p className="m-0 text-xs whitespace-normal text-secondary">{consent}</p>}
                    <div className="flex justify-end gap-2">
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
                    </div>
                </div>
            }
        >
            <Form logic={aiCreditsLogic} formKey="addFundsForm" className="flex flex-col gap-4">
                <LemonField name="amountUsd" label="Amount" help={`Minimum $${MINIMUM_AI_CREDIT_USD}`}>
                    {({ error }) => (
                        <div className="flex flex-col gap-2">
                            <div className="flex gap-2" role="group" aria-label="Amount" data-attr="ai-credits-amount">
                                {[...AI_CREDIT_PRESET_AMOUNTS_USD.map(String), OTHER_AMOUNT].map((choice) => {
                                    const selected = choice === amountChoice
                                    return (
                                        <button
                                            key={choice}
                                            type="button"
                                            aria-pressed={selected}
                                            onClick={() =>
                                                choice === OTHER_AMOUNT
                                                    ? setAddFundsFormValues({ customAmount: true })
                                                    : setAddFundsFormValues({
                                                          customAmount: false,
                                                          amountUsd: Number(choice),
                                                      })
                                            }
                                            className={cn(
                                                'h-11 flex-1 cursor-pointer rounded text-base',
                                                selected
                                                    ? 'border-2 border-accent bg-accent-highlight-secondary'
                                                    : 'border bg-surface-primary hover:bg-fill-highlight-100',
                                                choice === OTHER_AMOUNT ? 'font-medium text-secondary' : 'font-semibold'
                                            )}
                                        >
                                            {choice === OTHER_AMOUNT ? 'Other' : humanFriendlyCurrency(choice, 0)}
                                        </button>
                                    )
                                })}
                            </div>
                            {amountChoice === OTHER_AMOUNT && (
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
                    )}
                </LemonField>

                {/* The quote spans the modal's width, so it pulls out past the content padding. */}
                <div className="-mx-4 flex flex-col gap-2.5 border-y bg-fill-secondary px-4 py-4">
                    {quoteError ? (
                        <span className="text-danger">{quoteError}</span>
                    ) : quoteLoading || !quote ? (
                        <LemonSkeleton repeat={3} />
                    ) : (
                        <>
                            <div className="flex justify-between">
                                <span className="text-secondary">Purchase</span>
                                <span>{humanFriendlyCurrency(quote.amount_usd)}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-secondary">Tax</span>
                                <span>{humanFriendlyCurrency(quote.tax_usd)}</span>
                            </div>
                            <div className="flex justify-between border-t pt-2.5 text-base font-semibold">
                                <span>Total due today</span>
                                <span className="font-bold">{humanFriendlyCurrency(quote.total_usd)}</span>
                            </div>
                        </>
                    )}
                </div>

                <div className="flex flex-col gap-2">
                    <span className="text-sm font-semibold">Card</span>
                    {cardLoading ? (
                        <LemonSkeleton className="h-10" />
                    ) : cardOnFile ? (
                        <CardOnFile card={cardOnFile} />
                    ) : (
                        <span className="text-secondary">
                            No card on file. Add one in your billing details, then come back.
                        </span>
                    )}
                </div>

                {!reloadAlreadyOn && cardOnFile && (
                    <div className="flex flex-col gap-3 rounded border px-4 py-3.5">
                        <LemonField name="reloadEnabled">
                            {({ value, onChange }) => (
                                <LemonSwitch
                                    checked={value}
                                    onChange={onChange}
                                    label={
                                        <span className="flex flex-col">
                                            <span className="font-semibold">Automatic reload</span>
                                            {!value && (
                                                <span className="text-sm font-normal text-secondary">
                                                    Add credits when the balance runs low
                                                </span>
                                            )}
                                        </span>
                                    }
                                    fullWidth
                                    data-attr="ai-credits-add-funds-reload"
                                />
                            )}
                        </LemonField>
                        {addFundsForm.reloadEnabled && <ReloadAmountFields />}
                    </div>
                )}

                {purchaseError && <LemonBanner type="error">{purchaseError}</LemonBanner>}
            </Form>
        </LemonModal>
    )
}
