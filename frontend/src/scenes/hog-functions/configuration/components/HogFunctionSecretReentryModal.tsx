import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { HogFunctionConfigurationLogicProps } from '../hogFunctionConfigurationLogic'
import { hogFunctionSecretReentryLogic } from '../hogFunctionSecretReentryLogic'

export function HogFunctionSecretReentryModal({
    logicProps,
}: {
    logicProps: HogFunctionConfigurationLogicProps
}): JSX.Element {
    const logic = hogFunctionSecretReentryLogic(logicProps)
    const { prompt, request, secretValue, secretEntryValues, confirmDisabledReason } = useValues(logic)
    const { setSecretValue, setSecretEntry, cancelSecretReentry, confirmSecretReentry } = useActions(logic)

    return (
        <LemonModal
            isOpen={!!prompt}
            onClose={cancelSecretReentry}
            width={480}
            hasUnsavedInput={!!secretValue || Object.values(secretEntryValues).some(Boolean)}
            title="Enter the secret again"
            description="This change sends the secret to a new address, so enter it again for security."
            footer={
                <>
                    <LemonButton type="secondary" onClick={cancelSecretReentry}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={confirmSecretReentry}
                        disabledReason={confirmDisabledReason}
                        data-attr="hog-function-secret-reentry-confirm"
                    >
                        {request?.retry === 'test' ? 'Test function' : 'Save'}
                    </LemonButton>
                </>
            }
        >
            <form
                onSubmit={(e) => {
                    e.preventDefault()
                    confirmSecretReentry()
                }}
            >
                <LemonField.Pure label={prompt?.label}>
                    {prompt?.entryKeys ? (
                        <div className="flex flex-col gap-2">
                            {prompt.entryKeys.map((entryKey, index) => (
                                <div className="flex gap-2 items-center" key={entryKey}>
                                    <LemonInput value={entryKey} disabled className="flex-1 min-w-0" />
                                    <LemonInput
                                        type="password"
                                        className="flex-2 min-w-0 ph-no-capture"
                                        autoFocus={index === 0}
                                        value={secretEntryValues[entryKey] ?? ''}
                                        onChange={(value) => setSecretEntry(entryKey, value)}
                                        placeholder="Secret value"
                                    />
                                </div>
                            ))}
                        </div>
                    ) : (
                        <LemonInput
                            type="password"
                            className="ph-no-capture"
                            autoFocus
                            value={secretValue}
                            onChange={setSecretValue}
                            placeholder="Secret value"
                        />
                    )}
                </LemonField.Pure>
            </form>
        </LemonModal>
    )
}
