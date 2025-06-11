import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-8 mb-10">
            <NativeExternalDataSourceConfiguration />
            <NonNativeExternalDataSourceConfiguration />
            <SelfManagedExternalDataSourceConfiguration />
        </div>
    )
}
