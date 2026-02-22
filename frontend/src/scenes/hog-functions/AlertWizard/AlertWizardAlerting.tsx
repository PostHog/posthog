import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { CyclotronJobFiltersType } from '~/types'

import { AlertWizard } from './AlertWizard'
import { alertWizardLogic } from './alertWizardLogic'

export function AlertWizardAlerting(): JSX.Element {
    const { alertCreationView, subTemplateIds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    const hogFunctionFilterList = subTemplateIds
        .map(getFiltersFromSubTemplateId)
        .filter((f) => !!f) as CyclotronJobFiltersType[]

    if (alertCreationView === 'wizard') {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView('none')
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    setAlertCreationView('traditional')
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === 'traditional') {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
                extraControls={
                    <LemonButton type="secondary" size="small" onClick={() => setAlertCreationView('none')}>
                        Cancel
                    </LemonButton>
                }
            />
        )
    }

    return (
        <HogFunctionList
            forceFilterGroups={hogFunctionFilterList}
            type="internal_destination"
            extraControls={
                <LemonButton type="primary" size="small" onClick={() => setAlertCreationView('wizard')}>
                    New notification
                </LemonButton>
            }
        />
    )
}
