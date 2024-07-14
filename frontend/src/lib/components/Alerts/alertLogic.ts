import { connect, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail } from 'lib/utils'
import { getInsightId } from 'scenes/insights/utils'
import { urls } from 'scenes/urls'

import { AlertType } from '~/types'

import type { alertLogicType } from './alertLogicType'
import { alertsLogic, AlertsLogicProps } from './alertsLogic'

export interface AlertLogicProps extends AlertsLogicProps {
    id: number | 'new'
}

export const alertLogic = kea<alertLogicType>([
    path(['lib', 'components', 'Alerts', 'alertLogic']),
    props({} as AlertLogicProps),
    key(({ id, insightShortId }) => `${insightShortId}-${id ?? 'new'}`),
    connect(() => ({
        actions: [alertsLogic, ['loadAlerts']],
    })),

    loaders(({ props }) => ({
        alert: {
            __default: undefined as unknown as AlertType,
            loadAlert: async () => {
                if (props.id && props.id !== 'new') {
                    return await api.alerts.get(props.id)
                }
                return { anomaly_condition: { absoluteThreshold: {} } }
            },
        },
    })),

    forms(({ props, actions }) => ({
        alert: {
            defaults: {} as unknown as AlertType,
            errors: ({ name, target_value }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
                target_value: !target_value
                    ? 'This field is required.'
                    : !target_value.split(',').every((email) => isEmail(email))
                    ? 'All emails must be valid'
                    : undefined,
            }),
            submit: async (alert) => {
                const insightId = await getInsightId(props.insightShortId)

                const payload = {
                    ...alert,
                    insight: insightId,
                }

                const updatedAlert: AlertType =
                    props.id === 'new' ? await api.alerts.create(payload) : await api.alerts.update(props.id, payload)

                actions.resetAlert()

                if (updatedAlert.id !== props.id) {
                    router.actions.replace(urls.alerts(props.insightShortId))
                }

                actions.loadAlerts()
                actions.loadAlertSuccess(updatedAlert)
                lemonToast.success(`Alert saved.`)

                return updatedAlert
            },
        },
    })),

    urlToAction(({ actions }) => ({
        '/*/*/alerts/:id': () => {
            actions.loadAlert()
        },
    })),
])
