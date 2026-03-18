import { getCapturedChartConfigs } from './chartjs-mock'

export function expectNoNaN(): void {
    const allPoints = getCapturedChartConfigs().flatMap(({ config }) =>
        (config.data?.datasets ?? []).flatMap((ds) => ds.data ?? [])
    )
    for (const value of allPoints) {
        expect(value).not.toBeNaN()
    }
}
