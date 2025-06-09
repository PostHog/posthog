import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'

import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    return (
        <div className="flex flex-col gap-8 mb-10">
            <BaseCurrency />
            <NonNativeExternalDataSourceConfiguration />
            <SelfManagedExternalDataSourceConfiguration />
        </div>
    )
}
