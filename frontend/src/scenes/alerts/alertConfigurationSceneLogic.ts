import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'

import { AlertDetectorsConfig, AlertCalculationInterval } from '~/queries/schema/schema-general'
import { Insight } from '~/types'

import { createDefaultDetectorsConfig } from 'lib/components/Alerts/detectors'
import { AlertType, AlertTypeWrite } from 'lib/components/Alerts/types'
import { urls } from 'scenes/urls'

import type { alertConfigurationSceneLogicType } from './alertConfigurationSceneLogicType'

export interface AlertConfigurationSceneLogicProps {
    alertId?: string
    insightId?: string
}

export interface AlertFormValues {
    name: string
    enabled: boolean
    detectors: AlertDetectorsConfig | null
    calculation_interval: AlertCalculationInterval
    skip_weekend: boolean
    subscribed_users: number[]
}

const DEFAULT_FORM_VALUES: AlertFormValues = {
    name: '',
    enabled: true,
    detectors: createDefaultDetectorsConfig(),
    calculation_interval: AlertCalculationInterval.DAILY,
    skip_weekend: false,
    subscribed_users: [],
}

export const alertConfigurationSceneLogic = kea<alertConfigurationSceneLogicType>([
    path(['scenes', 'alerts', 'alertConfigurationSceneLogic']),
    props({} as AlertConfigurationSceneLogicProps),
    key((props) => props.alertId || props.insightId || 'new'),

    actions({
        setAlertFormValue: (key: keyof AlertFormValues, value: any) => ({ key, value }),
        deleteAlert: true,
    }),

    loaders(({ props }) => ({
        alert: [
            null as AlertType | null,
            {
                loadAlert: async () => {
                    if (!props.alertId) {
                        return null
                    }
                    const response = await api.alerts.get(props.alertId)
                    return response
                },
            },
        ],
        insight: [
            null as Insight | null,
            {
                loadInsight: async () => {
                    if (!props.insightId) {
                        return null
                    }
                    const response = await api.insights.get(props.insightId)
                    return response
                },
            },
        ],
    })),

    reducers({
        alertFormValues: [
            DEFAULT_FORM_VALUES,
            {
                setAlertFormValue: (state, { key, value }) => ({
                    ...state,
                    [key]: value,
                }),
                loadAlertSuccess: (state, { alert }) => {
                    if (!alert) {
                        return state
                    }
                    return {
                        name: alert.name || '',
                        enabled: alert.enabled,
                        detectors: alert.detectors || createDefaultDetectorsConfig(),
                        calculation_interval: alert.calculation_interval || AlertCalculationInterval.DAILY,
                        skip_weekend: alert.skip_weekend || false,
                        subscribed_users: alert.subscribed_users?.map((u) => u.id) || [],
                    }
                },
            },
        ],
    }),

    selectors({
        isNew: [(s) => [s.alert], (alert) => !alert],
        insightIdForSave: [
            (s) => [s.alert, s.insight, (_, props) => props],
            (alert, insight, props) => {
                if (alert?.insight?.id) {
                    return alert.insight.id
                }
                if (insight?.id) {
                    return insight.id
                }
                return props.insightId ? parseInt(props.insightId) : null
            },
        ],
    }),

    forms(({ values, props, actions }) => ({
        alertForm: {
            defaults: DEFAULT_FORM_VALUES,
            errors: (values) => ({
                name: !values.name ? 'Name is required' : undefined,
                detectors: !values.detectors?.groups?.length ? 'At least one detector is required' : undefined,
            }),
            submit: async (formValues) => {
                const insightId = values.insightIdForSave

                if (!insightId) {
                    throw new Error('No insight ID available')
                }

                const payload: Partial<AlertTypeWrite> = {
                    name: formValues.name,
                    enabled: formValues.enabled,
                    detectors: formValues.detectors,
                    calculation_interval: formValues.calculation_interval,
                    skip_weekend: formValues.skip_weekend,
                    subscribed_users: formValues.subscribed_users,
                    insight: insightId,
                    // Keep legacy fields for backward compatibility
                    condition: { type: 'absolute_value' as any },
                    threshold: { configuration: { type: 'absolute' as any, bounds: {} } },
                    config: { type: 'TrendsAlertConfig', series_index: 0 },
                }

                if (props.alertId) {
                    await api.alerts.update(props.alertId, payload)
                } else {
                    await api.alerts.create(payload)
                }

                // Navigate back to insight
                if (values.insight) {
                    router.actions.push(urls.insightView(values.insight.short_id))
                } else if (values.alert?.insight?.short_id) {
                    router.actions.push(urls.insightView(values.alert.insight.short_id))
                }
            },
        },
    })),

    listeners(({ props, values }) => ({
        deleteAlert: async () => {
            if (!props.alertId) {
                return
            }

            if (!confirm('Are you sure you want to delete this alert?')) {
                return
            }

            await api.alerts.delete(props.alertId)

            // Navigate back to insight
            if (values.insight) {
                router.actions.push(urls.insightView(values.insight.short_id))
            } else if (values.alert?.insight?.short_id) {
                router.actions.push(urls.insightView(values.alert.insight.short_id))
            } else {
                router.actions.push(urls.savedInsights())
            }
        },
    })),
])
