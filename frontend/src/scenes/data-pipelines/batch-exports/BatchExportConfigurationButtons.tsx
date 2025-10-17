import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { batchExportSceneLogic } from './BatchExportScene'
import {
    BatchExportConfigurationLogicProps,
    batchExportConfigurationLogic,
    getDefaultConfiguration,
} from './batchExportConfigurationLogic'

export function BatchExportConfigurationSaveButton(): JSX.Element {
    const { logicProps } = useValues(batchExportSceneLogic)
    const logic = batchExportConfigurationLogic(logicProps as BatchExportConfigurationLogicProps)
    const { isNew, isConfigurationSubmitting, configurationChanged } = useValues(logic)
    const { submitConfiguration } = useActions(logic)
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
    const { logicProps } = useValues(batchExportSceneLogic)
    const logic = batchExportConfigurationLogic(logicProps as BatchExportConfigurationLogicProps)
    const { isNew, isConfigurationSubmitting, configurationChanged, savedConfiguration, service } = useValues(logic)
    const { resetConfiguration } = useActions(logic)

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
