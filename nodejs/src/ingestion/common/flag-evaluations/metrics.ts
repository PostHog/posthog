import { Counter } from 'prom-client'

export const experimentFlagKeysLookupTotal = new Counter({
    name: 'ingestion_experiment_flag_keys_lookup_total',
    help: '$feature_flag_called events by whether their flag has a live experiment',
    labelNames: ['result'], // 'has_experiment' | 'no_experiment'
})
