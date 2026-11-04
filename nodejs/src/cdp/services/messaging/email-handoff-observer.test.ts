import { register } from 'prom-client'

import './email-handoff-observer'

describe('cdp_email_duplicate_handoff_total', () => {
    it('exposes a series at zero for each source before the first duplicate', async () => {
        const metric = await register.getSingleMetric('cdp_email_duplicate_handoff_total')!.get()

        expect(metric.values).toEqual([
            { labels: { source: 'transactional_api' }, value: 0 },
            { labels: { source: 'workflow' }, value: 0 },
        ])
    })
})
