import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { List, Select, Space, Switch } from 'antd'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRootPopupContainer } from '~/toolbar/utils'

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
                renderItem={(featureFlag) => {
                    const hasVariants = (featureFlag.filters?.multivariate?.variants?.length || 0) > 0
                    return (
                        <List.Item>
                            <List.Item.Meta
                                title={
                                    <Space>
                                        <Switch
                                            checked={!!combinedFlags[featureFlag.key]}
                                            onChange={(checked) =>
                                                setOverriddenFlag(
                                                    featureFlag.key,
                                                    hasVariants && checked
                                                        ? (featureFlag.filters?.multivariate?.variants[0]
                                                              ?.key as string)
                                                        : checked
                                                )
                                            }
                                        />
                                        <div>
                                            <code>
                                                <a
                                                    href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}feature_flags/${
                                                        featureFlag.id
                                                    }`}
                                                >
                                                    {featureFlag.key}
                                                </a>
                                            </code>
                                            {!!combinedFlags[featureFlag.key] && hasVariants ? (
                                                <div>
                                                    <Select
                                                        style={{ width: '100%' }}
                                                        value={
                                                            typeof combinedFlags[featureFlag.key] === 'string'
                                                                ? (combinedFlags[featureFlag.key] as string)
                                                                : undefined
                                                        }
                                                        onChange={(value) => setOverriddenFlag(featureFlag.key, value)}
                                                        getPopupContainer={getShadowRootPopupContainer}
                                                    >
                                                        {featureFlag.filters?.multivariate?.variants.map((variant) => (
                                                            <Select.Option key={variant.key} value={variant.key}>
                                                                {variant.key} - {variant.name} (
                                                                {variant.rollout_percentage}
                                                                %)
                                                            </Select.Option>
                                                        ))}
                                                    </Select>
                                                </div>
                                            ) : null}
                                        </div>
                                    </Space>
                                }
                            />
                        </List.Item>
                    )
                }}
            />
        </div>
    )
}
