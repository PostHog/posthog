import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'scenes/hog-functions/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'scenes/hog-functions/AlertWizard/alertWizardLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType } from '~/types'

import { SDK_DOCTOR_DESTINATIONS, SDK_DOCTOR_SUB_TEMPLATE_IDS, SDK_DOCTOR_TRIGGERS } from './sdkDoctorAlertingConfig'

const HOG_FUNCTION_FILTER_LIST = SDK_DOCTOR_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export interface SdkDoctorAlertingProps {
    onAlertCreated?: (hogFunctionId?: string) => void
}

export function SdkDoctorAlerting({ onAlertCreated }: SdkDoctorAlertingProps = {}): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: 'sdk-doctor',
        subTemplateIds: SDK_DOCTOR_SUB_TEMPLATE_IDS,
        triggers: SDK_DOCTOR_TRIGGERS,
        destinations: SDK_DOCTOR_DESTINATIONS,
        onAlertCreated,
    }

    return (
        <BindLogic logic={alertWizardLogic} props={wizardProps}>
            <SdkDoctorAlertingInner />
        </BindLogic>
    )
}

function SdkDoctorAlertingInner(): JSX.Element {
    const { alertCreationView, subTemplateIds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    if (alertCreationView === AlertCreationView.Wizard) {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('sdk_doctor_alert_creation_switched_to_traditional', {
                        source: 'wizard',
                    })
                    setAlertCreationView(AlertCreationView.Traditional)
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === AlertCreationView.Traditional) {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
                extraControls={
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setAlertCreationView(AlertCreationView.None)}
                    >
                        Cancel
                    </LemonButton>
                }
            />
        )
    }

    return (
        <HogFunctionList
            forceFilterGroups={HOG_FUNCTION_FILTER_LIST}
            type="internal_destination"
            returnTo={urls.sdkDoctor()}
            onDeleteHogFunction={(hogFunction) => {
                posthog.capture('sdk_doctor_alert_deleted', {
                    hog_function_id: hogFunction.id,
                })
            }}
            onEditHogFunction={(hogFunction) => {
                posthog.capture('sdk_doctor_alert_edit_clicked', {
                    hog_function_id: hogFunction.id,
                })
            }}
            extraControls={
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        posthog.capture('sdk_doctor_alert_creation_started', {
                            source: 'wizard_button',
                        })
                        setAlertCreationView(AlertCreationView.Wizard)
                    }}
                >
                    New notification
                </LemonButton>
            }
        />
    )
}
