import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-8 mb-10">
            <ConversionGoalsConfiguration />
            <NativeExternalDataSourceConfiguration />
            <NonNativeExternalDataSourceConfiguration />
            <SelfManagedExternalDataSourceConfiguration />
        </div>
    )
}
