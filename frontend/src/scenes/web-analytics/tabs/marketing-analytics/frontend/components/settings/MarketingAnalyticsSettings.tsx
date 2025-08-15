import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'

import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { SceneContent, SceneDivider, SceneTitleSection } from '~/layout/scenes/SceneContent'

export function MarketingAnalyticsSettings(): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <SceneContent className={cn(!newSceneLayout && 'gap-8 mb-10')}>
            {newSceneLayout && (
                <SceneTitleSection
                    name="Marketing analytics"
                    resourceType={{
                        type: 'marketing',
                        typePlural: 'marketing',
                    }}
                />
            )}
            <SceneDivider />
            <BaseCurrency />
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
