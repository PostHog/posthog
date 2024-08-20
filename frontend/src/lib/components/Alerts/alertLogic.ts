import { connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { isEmail } from 'lib/utils'
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
    key(({ id, insightId }) => `${insightId}-${id ?? 'new'}`),
    connect(() => ({
        actions: [alertsLogic, ['loadAlerts'], router, ['push']],
    })),

    loaders(({ props }) => ({
        alert: {
            __default: undefined as unknown as AlertType,
            loadAlert: async () => {
                if (props.id) {
                    return await api.alerts.get(props.insightId, props.id)
                }
                return {
                    enabled: true,
                }
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
                const payload = {
                    ...alert,
                    insight: props.insightId,
                }

                try {
                    const updatedAlert: AlertType = !props.id
                        ? await api.alerts.create(props.insightId, payload)
                        : await api.alerts.update(props.insightId, props.id, payload)

                    actions.resetAlert()

                    actions.loadAlerts()
                    actions.loadAlertSuccess(updatedAlert)
                    lemonToast.success(`Alert saved.`)

                    return updatedAlert
                } catch (error: any) {
                    lemonToast.error(`Error saving alert: ${error.detail}`)
                    throw error
                }
            },
        },
    })),

    listeners(({ props }) => ({
        submitAlertSuccess: () => {
            router.actions.push(urls.alerts(props.insightShortId))
        },
    })),

    urlToAction(({ actions }) => ({
        '/*/*/alerts/:id': () => {
            actions.loadAlert()
        },
    })),
])
