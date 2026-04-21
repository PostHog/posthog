import { register } from 'prom-client'

import { AGREEMENT_KIND, INGESTION_LAG_INDICATOR, INGESTION_LATENCY_GROUP, OBJECTIVE_KIND } from '../common/slas'
import { IngestionSlaBuilder } from './builder'

describe('IngestionSlaBuilder', () => {
    beforeEach(() => {
        register.clear()
    })

    describe('target gauge emission', () => {
        it('emits a gauge value per objective and agreement', async () => {
            new IngestionSlaBuilder()
                .group(INGESTION_LATENCY_GROUP, (latency) =>
                    latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                        ingestionLag
                            .objective('under_5s', { thresholdMs: 5000, targetRatio: 0.999 })
                            .agreement('under_60s', { thresholdMs: 60000, targetRatio: 0.99 })
                    )
                )
                .build({ pipeline: 'ingestion', lane: 'main' })

            const metrics = await register.getSingleMetricAsString('ingestion_slo_target_ratio')
            expect(metrics).toMatch(/ingestion_slo_target_ratio\{[^}]*name="under_5s"[^}]*\} 0\.999/)
            expect(metrics).toMatch(/ingestion_slo_target_ratio\{[^}]*name="under_60s"[^}]*\} 0\.99/)
            expect(metrics).toMatch(/kind="objective"[^}]*le="5000"|le="5000"[^}]*kind="objective"/)
            expect(metrics).toMatch(/kind="agreement"[^}]*le="60000"|le="60000"[^}]*kind="agreement"/)
        })
    })

    describe('observation', () => {
        it('observes values into the group histogram labeled by sli', async () => {
            const slas = new IngestionSlaBuilder()
                .group(INGESTION_LATENCY_GROUP, (latency) =>
                    latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                        ingestionLag.objective('under_5s', { thresholdMs: 5000, targetRatio: 0.999 })
                    )
                )
                .build({ pipeline: 'ingestion', lane: 'main' })

            const observer = slas.indicator(INGESTION_LAG_INDICATOR)
            observer.observe(3000)
            observer.observe(4500)
            observer.observe(9000)

            const out = await register.getSingleMetricAsString(INGESTION_LATENCY_GROUP.name)
            expect(out).toMatch(/_bucket\{[^}]*le="1000"[^}]*\} 0/)
            expect(out).toMatch(/_bucket\{[^}]*le="5000"[^}]*\} 2/)
            expect(out).toMatch(/_bucket\{[^}]*le="10000"[^}]*\} 3/)
            expect(out).toMatch(/_count\{[^}]*sli="ingestion_lag"[^}]*\} 3/)
        })
    })

    describe('compile-time checks', () => {
        // These tests document what TypeScript catches. They never run, so any
        // `@ts-expect-error` that stops erroring will fail the type check.
        it.skip('rejects thresholdMs values that are not group buckets', () => {
            new IngestionSlaBuilder().group(INGESTION_LATENCY_GROUP, (latency) =>
                latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                    // @ts-expect-error — 7000 is not in the group's bucket tuple
                    ingestionLag.objective('bad', { thresholdMs: 7000, targetRatio: 0.99 })
                )
            )
        })

        it.skip('rejects duplicate objective names within one indicator', () => {
            new IngestionSlaBuilder().group(INGESTION_LATENCY_GROUP, (latency) =>
                latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                    ingestionLag
                        .objective('under_1s', { thresholdMs: 1000, targetRatio: 0.99 })
                        // @ts-expect-error — name already used
                        .objective('under_1s', { thresholdMs: 5000, targetRatio: 0.9 })
                )
            )
        })

        it.skip('rejects duplicate indicator declarations within one group', () => {
            new IngestionSlaBuilder().group(INGESTION_LATENCY_GROUP, (latency) =>
                latency
                    .indicator(INGESTION_LAG_INDICATOR, (ingestionLag) => ingestionLag)
                    .indicator(
                        // @ts-expect-error — indicator already registered
                        INGESTION_LAG_INDICATOR,
                        (ingestionLag) => ingestionLag
                    )
            )
        })

        it.skip('rejects observe() for an indicator that was not declared', () => {
            const slas = new IngestionSlaBuilder().build({ pipeline: 'p', lane: 'l' })
            // @ts-expect-error — no indicators declared, so `I` is `never`
            slas.indicator(INGESTION_LAG_INDICATOR)
        })
    })

    it('kind labels distinguish objectives from agreements', async () => {
        new IngestionSlaBuilder()
            .group(INGESTION_LATENCY_GROUP, (latency) =>
                latency.indicator(INGESTION_LAG_INDICATOR, (ingestionLag) =>
                    ingestionLag
                        .objective('obj', { thresholdMs: 1000, targetRatio: 0.99 })
                        .agreement('agr', { thresholdMs: 5000, targetRatio: 0.99 })
                )
            )
            .build({ pipeline: 'p', lane: 'l' })

        const out = await register.getSingleMetricAsString('ingestion_slo_target_ratio')
        expect(out).toContain(`kind="${OBJECTIVE_KIND}"`)
        expect(out).toContain(`kind="${AGREEMENT_KIND}"`)
    })
})
