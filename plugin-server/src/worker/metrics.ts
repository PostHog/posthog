import { Summary } from 'prom-client'

export const pluginActionMsSummary = new Summary({
    name: 'plugin_action_ms',
    help: 'Time to run plugin action',
    labelNames: ['plugin_id', 'action', 'status'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
