import { getCapturedChartConfigs } from './chartjs-mock'

export function expectNoNaN(): void {
    for (const { config } of getCapturedChartConfigs()) {
        for (const ds of config.data?.datasets ?? []) {
            for (let i = 0; i < (ds.data ?? []).length; i++) {
                expect(ds.data![i]).not.toBeNaN()
            }
        }
    }
}
