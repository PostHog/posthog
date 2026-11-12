import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { SecretReentrySource, hogFunctionSecretReentryLogic } from '../hogFunctionSecretReentryLogic'

const CONFIRM_LABELS: Record<SecretReentrySource, string> = {
    save: 'Save',
    test: 'Test function',
    publish: 'Publish',
}

export function HogFunctionSecretReentryModal(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)
    const logic = hogFunctionSecretReentryLogic(logicProps)
    const { isOpen, prompt, secretValues, secretEntryValues, confirmDisabledReason } = useValues(logic)
    const { setSecretValue, setSecretEntry, cancelSecretReentry, confirmSecretReentry, clearSecretReentry } =
        useActions(logic)
    const secrets = prompt?.secrets ?? []
    const hasUnsavedInput =
        Object.values(secretValues).some(Boolean) ||
        Object.values(secretEntryValues).some((entries) => Object.values(entries).some(Boolean))

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={cancelSecretReentry}
            onAfterClose={clearSecretReentry}
            width={480}
            hasUnsavedInput={hasUnsavedInput}
            title={secrets.length > 1 ? 'Enter the secrets again' : 'Enter the secret again'}
            description="Changes to the code, inputs or mappings need every stored secret entered again."
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
                        {CONFIRM_LABELS[prompt?.source ?? 'save']}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {secrets.map(({ key, label, entryKeys }, index) =>
                    entryKeys ? (
                        <LemonField.Pure key={key} label={label}>
                            <div className="flex flex-col gap-2">
                                {entryKeys.map((entryKey, entryIndex) => (
                                    <div className="flex gap-2 items-center" key={entryKey}>
                                        <span className="flex-1 min-w-0 font-mono truncate" title={entryKey}>
                                            {entryKey}
                                        </span>
                                        <LemonInput
                                            type="password"
                                            className="flex-2 min-w-0 ph-no-capture"
                                            autoFocus={index === 0 && entryIndex === 0}
                                            aria-label={`Value for ${entryKey}`}
                                            value={secretEntryValues[key]?.[entryKey] ?? ''}
                                            onChange={(value) => setSecretEntry(key, entryKey, value)}
                                            onPressEnter={confirmSecretReentry}
                                            placeholder="Secret value"
                                        />
                                    </div>
                                ))}
                            </div>
                        </LemonField.Pure>
                    ) : (
                        <LemonField.Pure key={key} label={label} htmlFor={`hog-function-secret-reentry-${key}`}>
                            <LemonInput
                                id={`hog-function-secret-reentry-${key}`}
                                type="password"
                                className="ph-no-capture"
                                autoFocus={index === 0}
                                value={secretValues[key] ?? ''}
                                onChange={(value) => setSecretValue(key, value)}
                                onPressEnter={confirmSecretReentry}
                                placeholder="Secret value"
                            />
                        </LemonField.Pure>
                    )
                )}
            </div>
        </LemonModal>
    )
}
