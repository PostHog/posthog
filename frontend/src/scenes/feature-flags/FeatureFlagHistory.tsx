import { FeatureFlagTab } from 'scenes/feature-flags/FeatureFlagTabs'
import React from 'react'
import { FeatureFlagPageHeader } from 'scenes/feature-flags/FeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { useValues } from 'kea'
import { SceneLoading } from 'lib/utils'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'

export const scene: SceneExport = {
    component: FeatureFlagHistory,
    logic: featureFlagLogic,
}

export function FeatureFlagHistory(): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    return featureFlag && featureFlag.id ? (
        <>
            <FeatureFlagPageHeader activeTab={FeatureFlagTab.History} id={featureFlag.id} />
            <HistoryList id={featureFlag.id} type={'FeatureFlag'} />
        </>
    ) : (
        <SceneLoading />
    )
}
