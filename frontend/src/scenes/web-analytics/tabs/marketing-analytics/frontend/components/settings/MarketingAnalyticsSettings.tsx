import { useRef } from 'react'

import { BaseCurrency } from './BaseCurrency'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    const dataWarehouseTablesButtonRef = useRef<HTMLButtonElement>(null)

    return (
        <div className="flex flex-col gap-8 mb-10">
            <BaseCurrency />
            <NonNativeExternalDataSourceConfiguration buttonRef={dataWarehouseTablesButtonRef} />
        </div>
    )
}
