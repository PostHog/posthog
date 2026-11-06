import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { hogFunctionSecretReentryLogic } from '../hogFunctionSecretReentryLogic'

const SECRET_INPUT_ID = 'hog-function-secret-reentry-value'

export function HogFunctionSecretReentryModal(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)
    const logic = hogFunctionSecretReentryLogic(logicProps)
    const { isOpen, prompt, secretValue, secretEntryValues, confirmDisabledReason } = useValues(logic)
    const { setSecretValue, setSecretEntry, cancelSecretReentry, confirmSecretReentry, clearSecretReentry } =
        useActions(logic)
    const isDictionary = !!prompt?.entryKeys

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={cancelSecretReentry}
            onAfterClose={clearSecretReentry}
            width={480}
            hasUnsavedInput={!!secretValue || Object.values(secretEntryValues).some(Boolean)}
            title={isDictionary ? 'Enter the secret values again' : 'Enter the secret again'}
            description={
                isDictionary
                    ? 'Your edits send these secret values to a new address. Enter them to confirm.'
                    : 'Your edits send this secret to a new address. Enter its value to confirm.'
            }
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
                        {prompt?.source === 'test' ? 'Test function' : 'Save'}
                    </LemonButton>
                </>
            }
        >
            {prompt?.entryKeys ? (
                <LemonField.Pure label={prompt.label}>
                    <div className="flex flex-col gap-2">
                        {prompt.entryKeys.map((entryKey, index) => (
                            <div className="flex gap-2 items-center" key={entryKey}>
                                <span className="flex-1 min-w-0 font-mono truncate" title={entryKey}>
                                    {entryKey}
                                </span>
                                <LemonInput
                                    type="password"
                                    className="flex-2 min-w-0 ph-no-capture"
                                    autoFocus={index === 0}
                                    aria-label={`Value for ${entryKey}`}
                                    value={secretEntryValues[entryKey] ?? ''}
                                    onChange={(value) => setSecretEntry(entryKey, value)}
                                    onPressEnter={confirmSecretReentry}
                                    placeholder="Secret value"
                                />
                            </div>
                        ))}
                    </div>
                </LemonField.Pure>
            ) : (
                <LemonField.Pure label={prompt?.label} htmlFor={SECRET_INPUT_ID}>
                    <LemonInput
                        id={SECRET_INPUT_ID}
                        type="password"
                        className="ph-no-capture"
                        autoFocus
                        value={secretValue}
                        onChange={setSecretValue}
                        onPressEnter={confirmSecretReentry}
                        placeholder="Secret value"
                    />
                </LemonField.Pure>
            )}
        </LemonModal>
    )
}
