import './featureFlags.scss'

import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio, Switch, Row, Typography, List } from 'antd'
import { AnimatedCollapsible } from './AnimatedCollapsible'

export function FeatureFlags(): JSX.Element {
    const { userFlagsWithCalculatedInfo } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)

    return (
        <div className="toolbar-block">
            <List
                dataSource={userFlagsWithCalculatedInfo}
                renderItem={({
                    feature_flag,
                    value_for_user_without_override,
                    override,
                    hasVariants,
                    currentValue,
                }) => {
                    return (
                        <div className="feature-flag-row">
                            <Row
                                className={override ? 'feature-flag-row-header overridden' : 'feature-flag-row-header'}
                            >
                                <Typography.Text ellipsis className="feature-flag-title">
                                    {feature_flag.key}
                                </Typography.Text>
                                <Switch
                                    checked={!!currentValue}
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
                            </Row>

                            <AnimatedCollapsible collapsed={!hasVariants || !currentValue}>
                                <Row className={override ? 'variant-radio-group overridden' : 'variant-radio-group'}>
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
                                        {feature_flag.filters?.multivariate?.variants.map((variant) => (
                                            <Radio key={variant.key} value={variant.key}>
                                                {`${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`}
                                            </Radio>
                                        ))}
                                    </Radio.Group>
                                </Row>
                            </AnimatedCollapsible>
                        </div>
                    )
                }}
            />
        </div>
    )
}
