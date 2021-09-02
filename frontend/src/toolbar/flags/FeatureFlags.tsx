import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { List, Space, Switch } from 'antd'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export function FeatureFlags(): JSX.Element {
    const { apiURL } = useValues(toolbarLogic)
    const { featureFlagCount, sortedFeatureFlags, combinedFlags } = useValues(featureFlagsLogic)
    const { setOverriddenFlag } = useActions(featureFlagsLogic)

    return (
        <div className="toolbar-block">
            <p>Flags ({featureFlagCount})</p>

            <List
                itemLayout="horizontal"
                dataSource={sortedFeatureFlags}
                renderItem={(featureFlag) => (
                    <List.Item>
                        <List.Item.Meta
                            title={
                                <Space>
                                    <Switch
                                        checked={!!combinedFlags[featureFlag.key]}
                                        onChange={(checked) => setOverriddenFlag(featureFlag.key, checked)}
                                    />
                                    <code>
                                        <a
                                            href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}feature_flags/${
                                                featureFlag.id
                                            }`}
                                        >
                                            {featureFlag.key}
                                        </a>
                                    </code>
                                </Space>
                            }
                        />
                    </List.Item>
                )}
            />
        </div>
    )
}
