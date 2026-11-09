import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { organizationLogic } from 'scenes/organizationLogic'

import { aiCreditsLogic, MINIMUM_AI_CREDIT_USD } from './aiCreditsLogic'
import { AmountChoices } from './AmountChoices'
import { CardOnFile } from './CardOnFile'
import { QuoteSummary } from './QuoteSummary'
import { ReloadAmountFields } from './ReloadAmountFields'

function AddFundsFooter(): JSX.Element {
    const { isAddFundsFormSubmitting, quote, card, addFundsConsent } = useValues(aiCreditsLogic)
    const { closeAddFundsModal, submitAddFundsForm } = useActions(aiCreditsLogic)

    return (
        <div className="flex w-full flex-col gap-4">
            {addFundsConsent && <p className="m-0 text-xs whitespace-normal text-secondary">{addFundsConsent}</p>}
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
                        !card?.card
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
    )
}

function AutomaticReloadChoice(): JSX.Element {
    const { addFundsForm } = useValues(aiCreditsLogic)

    return (
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
    )
}

export function AddAICreditsModal(): JSX.Element {
    const { addFundsModalOpen, purchaseError, card, cardLoading, settings } = useValues(aiCreditsLogic)
    const { closeAddFundsModal } = useActions(aiCreditsLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const cardOnFile = card?.card ?? null

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
            footer={<AddFundsFooter />}
        >
            <Form logic={aiCreditsLogic} formKey="addFundsForm" className="flex flex-col gap-4">
                <LemonField name="amountUsd" label="Amount" help={`Minimum $${MINIMUM_AI_CREDIT_USD}`}>
                    {({ error }) => <AmountChoices error={error} />}
                </LemonField>

                <QuoteSummary />

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

                {!settings?.automatic_reload.enabled && cardOnFile && <AutomaticReloadChoice />}

                {purchaseError && <LemonBanner type="error">{purchaseError}</LemonBanner>}
            </Form>
        </LemonModal>
    )
}
