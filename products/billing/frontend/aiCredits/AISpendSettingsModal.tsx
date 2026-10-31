import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { aiCreditsLogic, automaticReloadConsent, cardLabel } from './aiCreditsLogic'
import { ReloadAmountFields } from './ReloadAmountFields'

export function AISpendSettingsModal(): JSX.Element {
    const { settingsModalOpen, spendSettingsForm, isSpendSettingsFormSubmitting, settings, card } =
        useValues(aiCreditsLogic)
    const { closeSettingsModal, submitSpendSettingsForm } = useActions(aiCreditsLogic)

    const cardOnFile = card?.card ?? null
    const turningReloadOn = spendSettingsForm.reloadEnabled && !settings?.automatic_reload.enabled

    return (
        <LemonModal
            isOpen={settingsModalOpen}
            onClose={closeSettingsModal}
            title="AI credit settings"
            width={560}
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
            <Form logic={aiCreditsLogic} formKey="spendSettingsForm" className="flex flex-col gap-4">
                <div className="flex flex-col gap-3">
                    <LemonField name="reloadEnabled">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Automatic reload"
                                fullWidth
                                disabledReason={
                                    !cardOnFile && !value ? 'Add a card to your billing details first' : undefined
                                }
                                data-attr="ai-credits-settings-reload"
                            />
                        )}
                    </LemonField>
                    {cardOnFile && <span className="text-secondary">Charges your {cardLabel(cardOnFile)}</span>}
                    {spendSettingsForm.reloadEnabled && (
                        <>
                            <ReloadAmountFields />
                            {turningReloadOn && cardOnFile && (
                                <p className="m-0 text-xs text-secondary">
                                    {automaticReloadConsent(cardOnFile, spendSettingsForm)}
                                </p>
                            )}
                        </>
                    )}
                </div>
                <LemonDivider />
                <LemonField
                    name="spendLimitUsd"
                    label="Organization spend limit"
                    help="The most your organization can spend on AI in a billing period. Leave empty for no limit."
                >
                    <LemonInput
                        type="number"
                        prefix={<span>$</span>}
                        min={0}
                        placeholder="No limit"
                        className="max-w-60"
                        data-attr="ai-credits-spend-limit"
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
