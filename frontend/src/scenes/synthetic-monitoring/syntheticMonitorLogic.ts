import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import type { syntheticMonitorLogicType } from './syntheticMonitorLogicType'
import { SyntheticMonitor } from './types'

export interface SyntheticMonitorLogicProps {
    id?: string
}

export const syntheticMonitorLogic = kea<syntheticMonitorLogicType>([
    path(['scenes', 'synthetic-monitoring', 'syntheticMonitorLogic']),
    props({} as SyntheticMonitorLogicProps),
    key((props) => props.id || 'new'),
    actions({
        setMonitor: (monitor: SyntheticMonitor | null) => ({ monitor }),
    }),
    loaders(({ props }) => ({
        monitor: [
            null as SyntheticMonitor | null,
            {
                loadMonitor: async () => {
                    if (!props.id || props.id === 'new') {
                        return null
                    }
                    return await api.syntheticMonitoring.get(props.id)
                },
            },
        ],
    })),
    forms(({ props, actions, values }) => ({
        monitorForm: {
            defaults: {
                name: '',
                url: '',
                frequency_minutes: 5 as const,
                regions: ['default'],
                method: 'GET',
                headers: null,
                body: null,
                expected_status_code: 200,
                timeout_seconds: 30,
                alert_enabled: true,
                alert_threshold_failures: 3,
                alert_recipient_ids: [],
                slack_integration_id: null,
            } as Partial<SyntheticMonitor>,
            errors: ({ name, url, expected_status_code, timeout_seconds }) => ({
                name: !name ? 'Name is required' : undefined,
                url: !url
                    ? 'URL is required'
                    : !url.startsWith('http://') && !url.startsWith('https://')
                    ? 'URL must start with http:// or https://'
                    : undefined,
                expected_status_code:
                    expected_status_code && (expected_status_code < 100 || expected_status_code >= 600)
                        ? 'Status code must be between 100 and 599'
                        : undefined,
                timeout_seconds:
                    timeout_seconds && (timeout_seconds < 1 || timeout_seconds > 300)
                        ? 'Timeout must be between 1 and 300 seconds'
                        : undefined,
            }),
            submit: async (monitor) => {
                try {
                    if (props.id && props.id !== 'new') {
                        const updated = await api.syntheticMonitoring.update(props.id, monitor)
                        lemonToast.success('Monitor updated successfully')
                        actions.setMonitor(updated)
                        router.actions.push(urls.syntheticMonitor(updated.id))
                    } else {
                        const created = await api.syntheticMonitoring.create(monitor)
                        lemonToast.success('Monitor created successfully')
                        router.actions.push(urls.syntheticMonitor(created.id))
                    }
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to save monitor')
                    throw error
                }
            },
        },
    })),
    reducers({
        isNew: [
            (_, props) => !props.id || props.id === 'new',
            {
                loadMonitorSuccess: (_, { monitor }) => !monitor,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.monitor, s.isNew],
            (monitor, isNew) => [
                { name: 'Synthetic monitoring', path: urls.syntheticMonitoring() },
                { name: isNew ? 'New monitor' : monitor?.name || 'Monitor' },
            ],
        ],
    }),
    listeners(({ values, actions }) => ({
        loadMonitorSuccess: ({ monitor }) => {
            if (monitor) {
                actions.setMonitorFormValues(monitor)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id && props.id !== 'new') {
            actions.loadMonitor()
        }
    }),
])
