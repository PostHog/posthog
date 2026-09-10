import { cleanup, render } from '@testing-library/react'

import { ensureJsdom, getHogChart, hoverUntilTooltip } from '@posthog/quill-charts/testing'

import { ForecastConditionType, ForecastConfig, ForecastEngineType } from '~/queries/schema/schema-general'

import type { ForecastSimulateResponseApi } from '../generated/api.schemas'
import { ForecastPreview } from './ForecastPreview'

ensureJsdom()

afterEach(() => {
    cleanup()
})

describe('ForecastPreview', () => {
    const forecastConfig: ForecastConfig = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 2,
    }

    async function hoverHeader(
        result: ForecastSimulateResponseApi,
        projectTimezone: string,
        index: number
    ): Promise<string | null | undefined> {
        const { container } = render(
            <ForecastPreview
                result={result}
                thresholdBounds={{ upper: 95 }}
                forecastConfig={forecastConfig}
                projectTimezone={projectTimezone}
            />
        )
        const chart = getHogChart(container)
        const totalLabels = result.dates.length + result.forecast_dates.length
        const tooltip = await hoverUntilTooltip(chart.element, index, totalLabels)
        return tooltip.querySelector('[data-attr="hog-chart-tooltip-label"]')?.textContent
    }

    // The chart hides its x-axis, so the tooltip header is the only date it shows. It stays a raw
    // API timestamp unless the axis carries the timezone to read each label in.
    it('names a daily bucket in the tooltip instead of the raw timestamp', async () => {
        const result: ForecastSimulateResponseApi = {
            data: [60, 70, 80],
            dates: ['2026-09-10T00:00:00', '2026-09-11T00:00:00', '2026-09-12T00:00:00'],
            interval: 'day',
            forecast_dates: ['2026-09-13T00:00:00', '2026-09-14T00:00:00'],
            forecast_yhat: [90, 100],
            forecast_lower: [85, 95],
            forecast_upper: [95, 105],
            target_projection: null,
        }

        expect(await hoverHeader(result, 'UTC', 3)).toBe('Sun, Sep 13, 2026')
    })

    // The engine sends history as project-local wall time with no zone, and hourly forecast buckets
    // with the project offset attached. Both forms have to name the hour the backend evaluated.
    it.each([
        ['a history bucket sent without a zone', 1, 'Sun, Sep 13, 07:00'],
        ['a forecast bucket sent with the project offset', 2, 'Sun, Sep 13, 09:00'],
    ])('reads %s in the project timezone', async (_name, index, expected) => {
        const result: ForecastSimulateResponseApi = {
            data: [60, 70],
            dates: ['2026-09-13 06:00:00', '2026-09-13 07:00:00'],
            interval: 'hour',
            forecast_dates: ['2026-09-13T09:00:00-04:00'],
            forecast_yhat: [90],
            forecast_lower: [85],
            forecast_upper: [95],
            target_projection: null,
        }

        expect(await hoverHeader(result, 'America/New_York', index)).toBe(expected)
    })
})
