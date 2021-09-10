import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio, Space, Switch, Row, Typography } from 'antd'
import { Collapse } from 'antd'

export function FeatureFlags(): JSX.Element {
    const { userFlags } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)

    return (
        <div className="toolbar-block">
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Flags ({userFlags.length})
            </h1>
            <Collapse>
                {userFlags.map(({ feature_flag, value_for_user_without_override, override }) => {
                    const hasVariants = (feature_flag.filters?.multivariate?.variants?.length || 0) > 0
                    const flagEnabled = override ? !!override?.override_value : !!value_for_user_without_override
                    const selectedVariant = hasVariants
                        ? override
                            ? override?.override_value
                            : value_for_user_without_override
                        : undefined
                    return (
                        <Collapse.Panel header={`${feature_flag.key}`} key={feature_flag.id as number}>
                            <>
                                <Row>
                                    <div style={{ flex: 1 }}>
                                        <Switch
                                            checked={flagEnabled}
                                            onChange={(checked) => {
                                                const newValue =
                                                    hasVariants && checked
                                                        ? (feature_flag.filters?.multivariate?.variants[0]
                                                              ?.key as string)
                                                        : checked
                                                if (newValue === value_for_user_without_override && override) {
                                                    deleteOverriddenUserFlag(override.id as number)
                                                } else {
                                                    setOverriddenUserFlag(feature_flag.id as number, newValue)
                                                }
                                            }}
                                        />
                                    </div>
                                    {override ? (
                                        <div>
                                            <Typography.Link
                                                style={{ color: '#f7a501' }}
                                                onClick={() => {
                                                    deleteOverriddenUserFlag(override.id as number)
                                                }}
                                            >
                                                Reset Override
                                            </Typography.Link>
                                        </div>
                                    ) : null}
                                </Row>
                                <Row style={{ marginTop: 10 }}>
                                    {hasVariants ? (
                                        <Radio.Group
                                            disabled={!flagEnabled}
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
                            </>
                        </Collapse.Panel>
                    )
                })}
            </Collapse>
        </div>
    )
}
