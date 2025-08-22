import { BaseCurrency } from 'lib/components/BaseCurrency/BaseCurrency'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ConversionGoalsConfiguration } from './ConversionGoalsConfiguration'
import { NativeExternalDataSourceConfiguration } from './NativeExternalDataSourceConfiguration'
import { NonNativeExternalDataSourceConfiguration } from './NonNativeExternalDataSourceConfiguration'
import { SelfManagedExternalDataSourceConfiguration } from './SelfManagedExternalDataSourceConfiguration'

export function MarketingAnalyticsSettings(): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <SceneContent className={cn(!newSceneLayout && 'gap-8 mb-10')}>
            {newSceneLayout && <SceneTitleSection name="Marketing analytics" description={null} />}
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
