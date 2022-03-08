import React, { useRef } from 'react'
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

    const historyListRef = useRef<any>()

    return (
        <div className="feature-flag">
            {featureFlag ? (
                <>
                    <FeatureFlagConfiguration.Form>
                        <PageHeader
                            title="Feature Flag"
                            tabbedPage={!!featureFlags[FEATURE_FLAGS.HISTORY_LOGS]}
                            buttons={<FeatureFlagConfiguration.HeaderButtons />}
                        />
                        <Tabs
                            tabPosition="top"
                            animated={false}
                            defaultActiveKey={FeatureFlagTab.Configuration}
                            onChange={(key: string) => {
                                if (key === FeatureFlagTab.History) {
                                    console.log({ ref: historyListRef?.current, key }, 'in on change')
                                    historyListRef?.current?.reload?.()
                                }
                            }}
                        >
                            <Tabs.TabPane tab="Configuration" key={FeatureFlagTab.Configuration}>
                                <FeatureFlagConfiguration.FormBody />
                            </Tabs.TabPane>
                            {!!featureFlags[FEATURE_FLAGS.HISTORY_LOGS] && (
                                <Tabs.TabPane
                                    tab={<span data-attr="feature-flag-history-tab">History</span>}
                                    key={FeatureFlagTab.History}
                                >
                                    <HistoryList id={featureFlag.id} type={'FeatureFlag'} ref={historyListRef} />
                                </Tabs.TabPane>
                            )}
                        </Tabs>
                    </FeatureFlagConfiguration.Form>
                </>
            ) : (
                // TODO: This should be skeleton loaders
                <SceneLoading />
            )}
        </div>
    )
}
