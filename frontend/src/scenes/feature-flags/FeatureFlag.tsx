import React from 'react'
import { Tabs } from 'antd'
import { useValues } from 'kea'
import { SceneLoading } from 'lib/utils'
import { featureFlagLogic } from './featureFlagLogic'
import { featureFlagLogic as currentFlagsLogic } from '../../lib/logic/featureFlagLogic'

import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import { SceneExport } from 'scenes/sceneTypes'
import { FEATURE_FLAGS } from 'lib/constants'
import { HistoryList } from 'lib/components/HistoryList/HistoryList'
import { FeatureFlagConfiguration } from './FeatureFlagConfiguration'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
}

export enum FeatureFlagTab {
    Configuration = 'configuration',
    History = 'history',
}

export function FeatureFlag(): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { featureFlags } = useValues(currentFlagsLogic)

    return (
        <div className="feature-flag">
            {featureFlag ? (
                <>
                    <PageHeader
                        title="Feature Flag"
                        tabbedPage={!!featureFlags[FEATURE_FLAGS.HISTORY_LOGS]}
                        buttons={<FeatureFlagConfiguration.HeaderButtons />}
                    />
                    <Tabs tabPosition="top" animated={false} defaultActiveKey={FeatureFlagTab.Configuration}>
                        <Tabs.TabPane tab="Configuration" key={FeatureFlagTab.Configuration}>
                            <FeatureFlagConfiguration.Form />
                        </Tabs.TabPane>
                        {!!featureFlags[FEATURE_FLAGS.HISTORY_LOGS] && (
                            <Tabs.TabPane
                                tab={<span data-attr="feature-flag-history-tab">History</span>}
                                key={FeatureFlagTab.History}
                            >
                                <HistoryList id={featureFlag.id} type={'FeatureFlag'} />
                            </Tabs.TabPane>
                        )}
                    </Tabs>
                </>
            ) : (
                // TODO: This should be skeleton loaders
                <SceneLoading />
            )}
        </div>
    )
}
