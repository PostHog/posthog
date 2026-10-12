import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'lib/components/Alerting/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
    decorateAlertName,
} from 'lib/components/Alerting/AlertWizard/alertWizardLogic'
import { Link } from 'lib/lemon-ui/Link'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { HogFunctionSubTemplateType } from '~/types'

import {
    buildSourceAlertFilterGroups,
    buildSourceAlertNameSuffix,
    buildSourceAlertPropertyFilters,
} from './sourceAlertFilters'
import { sourceAlertsLogic } from './sourceAlertsLogic'
import {
    SOURCE_ALERT_DESTINATIONS,
    SOURCE_ALERT_SUB_TEMPLATE_IDS,
    SOURCE_ALERT_TRIGGERS,
} from './sourceAlertWizardConfig'

export interface SourceAlertsProps {
    sourceId?: string
    sourceName?: string
}

export function SourceAlerts({ sourceId, sourceName }: SourceAlertsProps): JSX.Element {
    useMountedLogic(sourceAlertsLogic({ sourceId }))

    const wizardProps: AlertWizardLogicProps = {
        logicKey: `data-warehouse-alerts-${sourceId ?? 'project'}`,
        subTemplateIds: SOURCE_ALERT_SUB_TEMPLATE_IDS,
        triggers: SOURCE_ALERT_TRIGGERS,
        destinations: SOURCE_ALERT_DESTINATIONS,
        contextId: 'data-warehouse-alerts',
        presetPropertyFilters: buildSourceAlertPropertyFilters(sourceId),
        nameSuffix: buildSourceAlertNameSuffix(sourceId, sourceName),
        createdEventName: 'data_warehouse_alert_created',
    }

    return (
        <BindLogic logic={alertWizardLogic} props={wizardProps}>
            <SourceAlertsInner sourceId={sourceId} sourceName={sourceName} />
        </BindLogic>
    )
}

function SourceAlertsInner({ sourceId, sourceName }: SourceAlertsProps): JSX.Element {
    const { alertCreationView, subTemplateIds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    const surface = sourceId ? 'source_tab' : 'sources_page'

    if (alertCreationView === AlertCreationView.Wizard) {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('data_warehouse_alert_creation_switched_to_traditional', { surface })
                    setAlertCreationView(AlertCreationView.Traditional)
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === AlertCreationView.Traditional) {
        const properties = buildSourceAlertPropertyFilters(sourceId)
        const nameSuffix = buildSourceAlertNameSuffix(sourceId, sourceName)

        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id, subTemplate) => {
                    const filters = id ? getFiltersFromSubTemplateId(id) : undefined
                    if (!filters) {
                        return undefined
                    }
                    const overrides: Partial<HogFunctionSubTemplateType> = {
                        filters: properties.length > 0 ? { ...filters, properties } : filters,
                    }
                    if (nameSuffix && subTemplate?.name) {
                        overrides.name = decorateAlertName(subTemplate.name, null, nameSuffix)
                    }
                    return overrides
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
        <div className="flex flex-col gap-2">
            {sourceId ? (
                <p className="text-secondary mb-0">
                    These alerts apply to this source only. Alerts for all sources are on the{' '}
                    <Link to={urls.sources()}>Sources page</Link>.
                </p>
            ) : null}
            <HogFunctionList
                forceFilterGroups={buildSourceAlertFilterGroups(sourceId)}
                type="internal_destination"
                returnTo={sourceId ? urls.dataWarehouseSource(`managed-${sourceId}`, 'alerts') : urls.sources()}
                emptyText={
                    sourceId
                        ? 'No alerts for this source yet. Create an alert to send a message to Slack, Discord, Teams, or a webhook when a sync fails, recovers, or finishes.'
                        : 'No alerts yet. Create an alert to send a message to Slack, Discord, Teams, or a webhook when a sync fails, recovers, or finishes.'
                }
                onDeleteHogFunction={(hogFunction) => {
                    posthog.capture('data_warehouse_alert_deleted', { hog_function_id: hogFunction.id, surface })
                }}
                onEditHogFunction={(hogFunction) => {
                    posthog.capture('data_warehouse_alert_edit_clicked', { hog_function_id: hogFunction.id, surface })
                }}
                extraControls={
                    <LemonButton
                        type="primary"
                        size="small"
                        data-attr="new-data-warehouse-alert"
                        onClick={() => {
                            posthog.capture('data_warehouse_alert_creation_started', { surface })
                            setAlertCreationView(AlertCreationView.Wizard)
                        }}
                    >
                        New alert
                    </LemonButton>
                }
            />
        </div>
    )
}
