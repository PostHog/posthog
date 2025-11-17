import { Counter } from 'prom-client'

export const sideEffectResultCounter = new Counter({
    name: 'pipelines_side_effects_total',
    help: 'Total number of side effects processed with their results',
    labelNames: ['result'],
})
