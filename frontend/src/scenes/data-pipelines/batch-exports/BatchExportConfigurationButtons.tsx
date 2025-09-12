import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { batchExportConfigurationLogic } from './batchExportConfigurationLogic'

export function BatchExportConfigurationSaveButton(): JSX.Element {
    const { isNew, isConfigurationSubmitting, configurationChanged } = useValues(batchExportConfigurationLogic)
    const { submitConfiguration } = useActions(batchExportConfigurationLogic)
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
        >
            {isNew ? 'Create' : 'Save'}
        </LemonButton>
    )
}

export function BatchExportConfigurationClearChangesButton(): JSX.Element | null {
    const { isNew, isConfigurationSubmitting, configurationChanged } = useValues(batchExportConfigurationLogic)
    const { resetConfiguration } = useActions(batchExportConfigurationLogic)

    if (!configurationChanged) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            htmlType="reset"
            onClick={() => resetConfiguration()}
            disabledReason={
                !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
            }
        >
            {isNew ? 'Reset' : 'Clear changes'}
        </LemonButton>
    )
}

// const buttons = (
//     <>
//         <LemonButton
//             type="secondary"
//             htmlType="reset"
//             onClick={() =>
//                 isNew && service
//                     ? resetConfiguration(getDefaultConfiguration(service))
//                     : resetConfiguration(savedConfiguration)
//             }
//             disabledReason={
//                 !configurationChanged ? 'No changes' : isConfigurationSubmitting ? 'Saving in progress…' : undefined
//             }
//         >
//             {isNew ? 'Reset' : 'Cancel'}
//         </LemonButton>

//     </>
// )
