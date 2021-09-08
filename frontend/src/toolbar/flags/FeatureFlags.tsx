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
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Flags ({featureFlagCount})
            </h1>

            <List
                itemLayout="horizontal"
                dataSource={sortedFeatureFlags}
                renderItem={(featureFlag) => {
                    const hasVariants = (featureFlag.filters?.multivariate?.variants?.length || 0) > 0
                    return (
                        <List.Item key={featureFlag.id}>
                            <div>
                                <Space>
                                    <Switch
                                        checked={!!combinedFlags[featureFlag.key]}
                                        onChange={(checked) =>
                                            setOverriddenFlag(
                                                featureFlag.id as number,
                                                hasVariants && checked
                                                    ? (featureFlag.filters?.multivariate?.variants[0]?.key as string)
                                                    : checked
                                            )
                                        }
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
                                {!!combinedFlags[featureFlag.key] && hasVariants ? (
                                    <div style={{ marginTop: 10, padding: '0 8px 0 0px' }}>
                                        <Select
                                            style={{ width: '100%' }}
                                            value="Hey"
                                            // value={
                                            //     typeof combinedFlags[featureFlag.key] === 'string'
                                            //         ? (combinedFlags[featureFlag.key] as string)
                                            //         : undefined
                                            // }
                                            // // onChange={(value) => setOverriddenFlag(featureFlag.id as number, value)}
                                            getPopupContainer={getShadowRootPopupContainer}
                                        >
                                            {['Hey', 'hi', 'ho'].map((variant) => (
                                                <Select.Option key={variant} value={variant}>
                                                    {`${variant}`}
                                                </Select.Option>
                                            ))}
                                            {/* {featureFlag.filters?.multivariate?.variants.map((variant) => (
                                                <Select.Option key={variant.key} value={variant.key}>
                                                    {`${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`}
                                                </Select.Option>
                                            ))} */}
                                        </Select>
                                    </div>
                                ) : null}
                            </div>
                        </List.Item>
                    )
                }}
            />
        </div>
    )
}
