import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'lib/components/Alerting/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
    applyKindFilter,
    decorateAlertName,
} from 'lib/components/Alerting/AlertWizard/alertWizardLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, HogFunctionSubTemplateType } from '~/types'

import {
    HEALTH_ALERT_DESTINATIONS,
    HEALTH_ALERT_SUB_TEMPLATE_IDS,
    HEALTH_ALERT_TRIGGERS,
} from './healthAlertsWizardConfig'

const HOG_FUNCTION_FILTER_LIST = HEALTH_ALERT_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export interface HealthAlertsEntryPointProps {
    logicKey?: string
    // Restricts the resulting HogFunction's filter to a `kind IN (...)` set.
    // The central scene reads this from the `preset_kinds` URL search param so
    // per-page entry points (SDK Health, Pipeline Status) can deep-link in with
    // a scoped wizard. Omit (or pass an empty array) to leave filters
    // unrestricted (every kind).
    presetKinds?: string[]
}

export function HealthAlertsEntryPoint({
    logicKey = 'health-alerts',
    presetKinds,
}: HealthAlertsEntryPointProps = {}): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey,
        subTemplateIds: HEALTH_ALERT_SUB_TEMPLATE_IDS,
        triggers: HEALTH_ALERT_TRIGGERS,
        destinations: HEALTH_ALERT_DESTINATIONS,
        presetTriggerKinds: presetKinds,
    }

    return (
        <BindLogic logic={alertWizardLogic} props={wizardProps}>
            <HealthAlertsEntryPointInner />
        </BindLogic>
    )
}

function HealthAlertsEntryPointInner(): JSX.Element {
    const { alertCreationView, subTemplateIds, selectedKinds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    if (alertCreationView === AlertCreationView.Wizard) {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('health_alerts_creation_switched_to_traditional', { source: 'wizard' })
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
                getConfigurationOverrides={(_id, subTemplate) => {
                    if (!subTemplate) {
                        return undefined
                    }
                    const overrides: Partial<HogFunctionSubTemplateType> = {}
                    const filters = applyKindFilter(subTemplate.filters, selectedKinds)
                    if (filters && filters !== subTemplate.filters) {
                        overrides.filters = filters
                    }
                    if (selectedKinds && selectedKinds.length > 0) {
                        if (subTemplate.name) {
                            overrides.name = decorateAlertName(subTemplate.name, selectedKinds)
                        }
                        if (subTemplate.description) {
                            overrides.description = decorateAlertName(subTemplate.description, selectedKinds)
                        }
                    }
                    return Object.keys(overrides).length > 0 ? overrides : undefined
                }}
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
            returnTo={urls.healthAlerts(selectedKinds ?? undefined)}
            onDeleteHogFunction={(hogFunction) => {
                posthog.capture('health_alerts_deleted', { hog_function_id: hogFunction.id })
            }}
            onEditHogFunction={(hogFunction) => {
                posthog.capture('health_alerts_edit_clicked', { hog_function_id: hogFunction.id })
            }}
            extraControls={
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        posthog.capture('health_alerts_creation_started', { source: 'wizard_button' })
                        setAlertCreationView(AlertCreationView.Wizard)
                    }}
                >
                    New health alert
                </LemonButton>
            }
        />
    )
}
