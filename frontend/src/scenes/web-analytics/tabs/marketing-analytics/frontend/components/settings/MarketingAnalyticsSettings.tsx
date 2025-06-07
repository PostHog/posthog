import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-8 mb-10">
            <NonNativeExternalDataSourceConfiguration />
        </div>
    )
}
