import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'

import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-8 mb-10">
            <BaseCurrency />
            <ConversionGoalsConfiguration />
            <NativeExternalDataSourceConfiguration />
            <NonNativeExternalDataSourceConfiguration />
            <SelfManagedExternalDataSourceConfiguration />
        </div>
    )
}
