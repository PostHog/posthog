import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings({
    hideTitle = false,
    hideBaseCurrency = false,
}: {
    hideTitle?: boolean
    hideBaseCurrency?: boolean
}): JSX.Element {
    return (
        <SceneContent>
            {!hideTitle && (
                <SceneTitleSection
                    name="Marketing settings"
                    description={null}
                    resourceType={{
                        type: 'marketing_settings',
                    }}
                />
            )}
            {!hideBaseCurrency && (
                <>
                    <SceneDivider />
                    <BaseCurrency />
                </>
            )}
            <SceneDivider />
            <ConversionGoalsConfiguration />
            <SceneDivider />
            <NativeExternalDataSourceConfiguration />
            <SceneDivider />
            <NonNativeExternalDataSourceConfiguration />
            <SceneDivider />
            <SelfManagedExternalDataSourceConfiguration />
        </SceneContent>
    )
}
