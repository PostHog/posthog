import React from 'react'
import { useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { List, Space, Switch } from 'antd'

export function FeatureFlags(): JSX.Element {
    const { featureFlagCount, sortedFeatureFlags, enabledFeatureFlags } = useValues(featureFlagsLogic)
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
                                        checked={enabledFeatureFlags.includes(featureFlag.key)}
                                        onChange={(checked) => {
                                            const newFlags = checked
                                                ? [...enabledFeatureFlags, featureFlag.key]
                                                : enabledFeatureFlags.filter((flag) => flag !== featureFlag.key)

                                            ;(window['posthog'] as any).persistence.register({
                                                $override_feature_flags: newFlags,
                                            })
                                            ;(window['posthog'] as any).persistence.receivedFeatureFlags(newFlags)
                                        }}
                                    />
                                    <code>{featureFlag.key}</code>
                                </Space>
                            }
                        />
                    </List.Item>
                )}
            />
        </div>
    )
}
