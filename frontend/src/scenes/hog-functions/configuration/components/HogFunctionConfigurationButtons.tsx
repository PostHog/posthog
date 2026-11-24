import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

export function HogFunctionConfigurationSaveButton(): JSX.Element {
    const {
        configuration,
        configurationChanged,
        template,
        isConfigurationSubmitting,
        willReEnableOnSave,
        willChangeEnabledOnSave,
        hogFunction,
        inputsDiff,
    } = useValues(hogFunctionConfigurationLogic)
    const { submitConfiguration } = useActions(hogFunctionConfigurationLogic)
    return (
        <LemonButton
            type="primary"
            htmlType="submit"
            onClick={submitConfiguration}
            loading={isConfigurationSubmitting}
            disabledReason={
                inputsDiff
                    ? 'Accept or reject the suggested inputs first'
                    : !configurationChanged && hogFunction
                      ? 'No changes'
                      : undefined
            }
            size="small"
        >
            {template ? 'Create' : 'Save'}
            {willReEnableOnSave
                ? ' & re-enable'
                : willChangeEnabledOnSave
                  ? ` & ${configuration.enabled ? 'enable' : 'disable'}`
                  : ''}
        </LemonButton>
    )
}

export function HogFunctionConfigurationClearChangesButton(): JSX.Element | null {
    const { configurationChanged, isConfigurationSubmitting } = useValues(hogFunctionConfigurationLogic)
    const { resetForm } = useActions(hogFunctionConfigurationLogic)

    if (!configurationChanged) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            htmlType="reset"
            onClick={() => resetForm()}
            disabledReason={
                !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
            }
            size="small"
        >
            Clear changes
        </LemonButton>
    )
}
