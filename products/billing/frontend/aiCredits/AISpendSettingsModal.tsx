import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { organizationLogic } from 'scenes/organizationLogic'

import { aiCreditsLogic, automaticReloadConsent, cardShortLabel } from './aiCreditsLogic'
import { ReloadAmountFields } from './ReloadAmountFields'

export function AISpendSettingsModal(): JSX.Element {
    const {
        settingsModalOpen,
        spendSettingsForm,
        isSpendSettingsFormSubmitting,
        settings,
        card,
        spendSummary,
        reloadedThisPeriodText,
    } = useValues(aiCreditsLogic)
    const { closeSettingsModal, submitSpendSettingsForm } = useActions(aiCreditsLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const cardOnFile = card?.card ?? null
    const turningReloadOn = spendSettingsForm.reloadEnabled && !settings?.automatic_reload.enabled

    return (
        <LemonModal
            isOpen={settingsModalOpen}
            onClose={closeSettingsModal}
            title="AI spend settings"
            description={
                currentOrganization ? (
                    <>
                        For <span className="font-semibold text-primary">{currentOrganization.name}</span>
                    </>
                ) : undefined
            }
            width={640}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeSettingsModal}
                        disabledReason={isSpendSettingsFormSubmitting ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitSpendSettingsForm}
                        loading={isSpendSettingsFormSubmitting}
                        data-attr="ai-credits-save-settings"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={aiCreditsLogic} formKey="spendSettingsForm" className="flex flex-col gap-5">
                <div className="flex flex-col gap-3 rounded border px-4 py-3.5">
                    <LemonField name="reloadEnabled">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label={
                                    <span className="flex flex-col">
                                        <span className="font-semibold">Automatic reload</span>
                                        <span className="text-sm font-normal text-secondary">
                                            {cardOnFile ? cardShortLabel(cardOnFile) : 'No card on file'}
                                        </span>
                                    </span>
                                }
                                fullWidth
                                disabledReason={
                                    !cardOnFile && !value ? 'Add a card to your billing details first' : undefined
                                }
                                data-attr="ai-credits-settings-reload"
                            />
                        )}
                    </LemonField>
                    {spendSettingsForm.reloadEnabled && (
                        <>
                            <ReloadAmountFields />
                            {turningReloadOn && cardOnFile ? (
                                <p className="m-0 text-xs text-secondary">
                                    {automaticReloadConsent(cardOnFile, spendSettingsForm)}
                                </p>
                            ) : (
                                reloadedThisPeriodText && (
                                    <span className="text-xs text-tertiary">{reloadedThisPeriodText}</span>
                                )
                            )}
                        </>
                    )}
                </div>

                <div className="flex flex-col gap-2 border-t pt-5">
                    <span className="font-semibold">Organization spend limit</span>
                    <span className="text-sm text-secondary">
                        The most your organization can spend on AI in a billing period.
                    </span>
                    <div className="flex items-start gap-3">
                        <LemonField name="spendLimitUsd" className="max-w-60 flex-1">
                            <LemonInput
                                type="number"
                                prefix={<span>$</span>}
                                min={0}
                                placeholder="No limit"
                                disabled={spendSettingsForm.noSpendLimit}
                                data-attr="ai-credits-spend-limit"
                            />
                        </LemonField>
                        <LemonField name="noSpendLimit">
                            {({ value, onChange }) => (
                                <LemonCheckbox
                                    checked={value}
                                    onChange={onChange}
                                    label="No limit"
                                    className="h-9"
                                    data-attr="ai-credits-no-spend-limit"
                                />
                            )}
                        </LemonField>
                    </div>
                    {spendSummary && (
                        <span className="text-xs text-tertiary">
                            {humanFriendlyCurrency(spendSummary.spendUsd)} spent this period · resets{' '}
                            {spendSummary.periodEnd.format('MMM D')}
                        </span>
                    )}
                </div>
            </Form>
        </LemonModal>
    )
}
