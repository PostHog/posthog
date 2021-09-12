import './featureFlags.scss'

import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio, Space, Switch, Row, Typography } from 'antd'
import { Collapse } from 'antd'

export function FeatureFlags(): JSX.Element {
    const { userFlagsWithCalculatedInfo } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)

    return (
        <div className="toolbar-block">
            <h1 className="section-title" style={{ paddingTop: 4 }}>
                Flags ({userFlagsWithCalculatedInfo.length})
            </h1>
            <Collapse>
                {userFlagsWithCalculatedInfo.map(
                    ({ feature_flag, value_for_user_without_override, override, hasVariants, currentValue }) => {
                        return (
                            <Collapse.Panel header={`${feature_flag.key}`} key={feature_flag.id as number}>
                                <>
                                    <Row>
                                        <Typography.Text style={{ flex: 1 }}>
                                            <Typography.Text code>{currentValue?.toString()}</Typography.Text>
                                        </Typography.Text>
                                        {override ? (
                                            <Typography.Link
                                                style={{ color: '#f7a501' }}
                                                onClick={() => {
                                                    deleteOverriddenUserFlag(override.id as number)
                                                }}
                                            >
                                                (Reset)
                                            </Typography.Link>
                                        ) : null}
                                    </Row>
                                    <Row style={{ marginTop: 10 }}>
                                        <Typography.Text strong>Edit Flag:</Typography.Text>
                                    </Row>
                                    <Row style={{ marginTop: 7 }}>
                                        <Typography.Text style={{ marginRight: 5 }}>Enabled:</Typography.Text>
                                        <Switch
                                            checked={!!currentValue}
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
                                    </Row>
                                    {hasVariants ? (
                                        <Row style={{ marginTop: 7 }}>
                                            <Radio.Group
                                                disabled={!currentValue}
                                                value={currentValue}
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
                                        </Row>
                                    ) : null}
                                </>
                            </Collapse.Panel>
                        )
                    }
                )}
            </Collapse>
        </div>
    )
}
