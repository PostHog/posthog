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
    } = useValues(hogFunctionConfigurationLogic)
    const { submitConfiguration } = useActions(hogFunctionConfigurationLogic)
    return (
        <LemonButton
            type="primary"
            htmlType="submit"
            onClick={submitConfiguration}
            loading={isConfigurationSubmitting}
            disabledReason={!configurationChanged && hogFunction ? 'No changes' : undefined}
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
