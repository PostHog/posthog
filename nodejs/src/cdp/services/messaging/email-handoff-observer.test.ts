import { register } from 'prom-client'

import { RedisV2 } from '~/common/redis/redis-v2'

import { createExampleInvocation } from '../../_tests/fixtures'
import { EmailHandoffObserver } from './email-handoff-observer'

async function counterValue(name: string, labels: Record<string, string>): Promise<number> {
    const metric = await register.getSingleMetric(name)!.get()
    const sample = metric.values.find((value) =>
        Object.entries(labels).every(([key, labelValue]) => value.labels[key] === labelValue)
    )
    return sample?.value ?? 0
}

describe('EmailHandoffObserver', () => {
    it('exposes every series at zero before the first observation', async () => {
        const duplicates = await register.getSingleMetric('cdp_email_duplicate_handoff_total')!.get()
        const observations = await register.getSingleMetric('cdp_email_handoff_observations_total')!.get()

        expect(duplicates.values).toEqual([
            { labels: { source: 'transactional_api' }, value: 0 },
            { labels: { source: 'workflow' }, value: 0 },
        ])
        expect(observations.values).toHaveLength(8)
        expect(observations.values.every((sample) => sample.value === 0)).toBe(true)
    })

    it('drops an observation while too many writes are still waiting on Valkey', async () => {
        const stalledValkey: RedisV2 = {
            useClient: () => new Promise(() => {}),
            usePipeline: () => new Promise(() => {}),
        }
        const observer = new EmailHandoffObserver(stalledValkey)
        const dropped = { source: 'workflow', result: 'dropped' }
        const before = await counterValue('cdp_email_handoff_observations_total', dropped)

        for (let index = 0; index < 17; index++) {
            observer.observe(createExampleInvocation(), 'workflow')
        }

        expect(await counterValue('cdp_email_handoff_observations_total', dropped)).toBe(before + 1)
    })
})
