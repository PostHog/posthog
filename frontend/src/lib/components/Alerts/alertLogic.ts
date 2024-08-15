import { connect, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail } from 'lib/utils'
import { getInsightId } from 'scenes/insights/utils'
import { urls } from 'scenes/urls'

import { AlertType } from '~/queries/schema'

import type { alertLogicType } from './alertLogicType'
import { alertsLogic, AlertsLogicProps } from './alertsLogic'

export interface AlertLogicProps extends AlertsLogicProps {
    id?: string
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
                if (props.id) {
                    return await api.alerts.get(props.id)
                }
                return { condition: { absoluteThreshold: {} } }
            },
        },
    })),

    forms(({ props, actions }) => ({
        alert: {
            defaults: {} as unknown as AlertType,
            errors: ({ name, notification_targets }) => ({
                name: !name ? 'You need to give your alert a name' : undefined,
                notification_targets: !notification_targets?.email?.every((email) => isEmail(email))
                    ? {
                          email: ['All emails must be valid'],
                      }
                    : undefined,
            }),
            submit: async (alert) => {
                const insightId = await getInsightId(props.insightShortId)

                const payload = {
                    ...alert,
                    insight: insightId,
                }

                const updatedAlert: AlertType = !props.id
                    ? await api.alerts.create(payload)
                    : await api.alerts.update(props.id, payload)

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
