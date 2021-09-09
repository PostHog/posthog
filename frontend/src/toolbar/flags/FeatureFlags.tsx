import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { List, Radio, Space, Switch, Row, Typography } from 'antd'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export function FeatureFlags(): JSX.Element {
    const { apiURL } = useValues(toolbarLogic)
    const { userFlags } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)

    return (
        <div className="toolbar-block">
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Flags ({userFlags.length})
            </h1>

            <List
                itemLayout="horizontal"
                dataSource={userFlags}
                renderItem={({ feature_flag, value_for_user_without_override, override }) => {
                    const hasVariants = (feature_flag.filters?.multivariate?.variants?.length || 0) > 0
                    const flagEnabled = override ? !!override?.override_value : !!value_for_user_without_override
                    const selectedVariant = hasVariants
                        ? override
                            ? override?.override_value
                            : value_for_user_without_override
                        : undefined
                    return (
                        <div
                            style={{
                                padding: '15px 0 15px 0',
                                borderBottom: '1px solid #d9d9d9',
                            }}
                            key={feature_flag.id}
                        >
                            <Row>
                                <Space>
                                    <Switch
                                        checked={flagEnabled}
                                        onChange={(checked) => {
                                            const newValue =
                                                hasVariants && checked
                                                    ? (feature_flag.filters?.multivariate?.variants[0]?.key as string)
                                                    : checked
                                            if (newValue === value_for_user_without_override && override) {
                                                deleteOverriddenUserFlag(override.id as number)
                                            } else {
                                                setOverriddenUserFlag(feature_flag.id as number, newValue)
                                            }
                                        }}
                                    />
                                    <code>
                                        <a
                                            href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}feature_flags/${
                                                feature_flag.id
                                            }`}
                                        >
                                            {feature_flag.key}
                                        </a>
                                    </code>
                                </Space>
                            </Row>
                            <Row style={{ marginTop: 10 }}>
                                {!!flagEnabled && hasVariants ? (
                                    <Radio.Group
                                        value={selectedVariant}
                                        onChange={(event) => {
                                            const newValue = event.target.value
                                            if (newValue === value_for_user_without_override && override) {
                                                deleteOverriddenUserFlag(override.id as number)
                                            } else {
                                                setOverriddenUserFlag(feature_flag.id as number, newValue)
                                            }
                                        }}
                                    >
                                        <Space direction="vertical">
                                            {feature_flag.filters?.multivariate?.variants.map((variant) => (
                                                <Radio key={variant.key} value={variant.key}>
                                                    {`${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`}
                                                </Radio>
                                            ))}
                                        </Space>
                                    </Radio.Group>
                                ) : null}
                            </Row>
                            {override ? (
                                <Row style={{ marginTop: 7 }}>
                                    <Typography.Paragraph style={{ margin: 0 }}>
                                        {`Flag Overridden `}
                                        <Typography.Link
                                            style={{ color: 'red' }}
                                            onClick={() => {
                                                deleteOverriddenUserFlag(override.id as number)
                                            }}
                                        >
                                            (Remove)
                                        </Typography.Link>
                                    </Typography.Paragraph>
                                </Row>
                            ) : null}
                        </div>
                    )
                }}
            />
        </div>
    )
}
