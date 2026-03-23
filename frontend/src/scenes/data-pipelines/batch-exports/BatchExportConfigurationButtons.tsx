import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { batchExportConfigFormLogic, getDefaultConfiguration } from './batchExportConfigFormLogic'

export function BatchExportConfigurationSaveButton(): JSX.Element {
    const { isNew, isConfigurationSubmitting, configurationChanged } = useValues(batchExportConfigFormLogic)
    const { submitConfiguration } = useActions(batchExportConfigFormLogic)
    return (
        <LemonButton
            type="primary"
            htmlType="submit"
            onClick={submitConfiguration}
            loading={isConfigurationSubmitting}
            disabledReason={
                !configurationChanged
                    ? 'No changes to save'
                    : isConfigurationSubmitting
                      ? 'Saving in progress…'
                      : undefined
            }
            size="small"
        >
            {isNew ? 'Create' : 'Save'}
        </LemonButton>
    )
}

export function BatchExportConfigurationClearChangesButton(): JSX.Element | null {
    const { isNew, isConfigurationSubmitting, configurationChanged, savedConfiguration, service } =
        useValues(batchExportConfigFormLogic)
    const { resetConfiguration } = useActions(batchExportConfigFormLogic)

    if (!configurationChanged) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            htmlType="reset"
            onClick={() =>
                isNew && service
                    ? resetConfiguration(getDefaultConfiguration(service))
                    : resetConfiguration(savedConfiguration)
            }
            disabledReason={
                !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
            }
            size="small"
        >
            {isNew ? 'Reset' : 'Clear changes'}
        </LemonButton>
    )
}
