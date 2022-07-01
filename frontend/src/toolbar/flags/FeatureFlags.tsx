import './featureFlags.scss'

import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio, Switch, Row, Typography, List, Input } from 'antd'
import { AnimatedCollapsible } from '../../lib/components/AnimatedCollapsible'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/components/icons'

export function FeatureFlags(): JSX.Element {
    const { searchTerm, filteredFlags } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag, setSearchTerm } = useActions(featureFlagsLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-block">
            <div className="local-feature-flag-override-note">
                <Typography.Text>Note, overriding feature flags below will only affect this browser.</Typography.Text>
            </div>
            <>
                <Input.Search
                    allowClear
                    autoFocus
                    placeholder="Search"
                    value={searchTerm}
                    className={'feature-flag-row'}
                    onChange={(e) => setSearchTerm(e.target.value)}
                />
                <List
                    dataSource={filteredFlags}
                    renderItem={({ feature_flag, value, hasOverride, hasVariants, currentValue }) => {
                        return (
                            <div className={'feature-flag-row'}>
                                <Row
                                    className={
                                        hasOverride ? 'feature-flag-row-header overridden' : 'feature-flag-row-header'
                                    }
                                >
                                    <Typography.Text ellipsis className="feature-flag-title">
                                        {feature_flag.key}
                                    </Typography.Text>
                                    <a
                                        className="feature-flag-external-link"
                                        href={`${apiURL}${
                                            feature_flag.id ? urls.featureFlag(feature_flag.id) : urls.featureFlags()
                                        }`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        <IconOpenInNew />
                                    </a>
                                    <Switch
                                        checked={!!currentValue}
                                        onChange={(checked) => {
                                            const newValue =
                                                hasVariants && checked
                                                    ? (feature_flag.filters?.multivariate?.variants[0]?.key as string)
                                                    : checked
                                            if (newValue === value && hasOverride) {
                                                deleteOverriddenUserFlag(feature_flag.key)
                                            } else {
                                                setOverriddenUserFlag(feature_flag.key, newValue)
                                            }
                                        }}
                                    />
                                </Row>

                                <AnimatedCollapsible collapsed={!hasVariants || !currentValue}>
                                    <Row
                                        className={
                                            hasOverride ? 'variant-radio-group overridden' : 'variant-radio-group'
                                        }
                                    >
                                        <Radio.Group
                                            disabled={!currentValue}
                                            value={currentValue}
                                            onChange={(event) => {
                                                const newValue = event.target.value
                                                if (newValue === value && hasOverride) {
                                                    deleteOverriddenUserFlag(feature_flag.key)
                                                } else {
                                                    setOverriddenUserFlag(feature_flag.key, newValue)
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
            </>
        </div>
    )
}
