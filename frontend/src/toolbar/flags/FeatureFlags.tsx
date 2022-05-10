import './featureFlags.scss'

import React from 'react'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio, Switch, Row, Typography, List, Button, Input } from 'antd'
import { AnimatedCollapsible } from '../../lib/components/AnimatedCollapsible'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/components/icons'

export function FeatureFlags(): JSX.Element {
    const { showLocalFeatureFlagWarning, searchTerm, filteredFlags } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag, setShowLocalFeatureFlagWarning, setSearchTerm } =
        useActions(featureFlagsLogic)
    const { apiURL, posthog } = useValues(toolbarLogic)

    return (
        <div className="toolbar-block">
            {showLocalFeatureFlagWarning ? (
                <div className="local-feature-flag-override-warning">
                    <Typography.Text>
                        <Typography.Text type="warning" strong>
                            Warning:
                        </Typography.Text>{' '}
                        It looks like you've previously used the developer console to set local feature flags. To use
                        feature flags in the toolbar, please clear them below.
                    </Typography.Text>
                    <div>
                        <Button
                            type="primary"
                            onClick={() => {
                                posthog?.feature_flags.override(false)
                                setShowLocalFeatureFlagWarning(false)
                            }}
                        >
                            Clear locally set feature flags
                        </Button>
                    </div>
                </div>
            ) : (
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
                        renderItem={({
                            feature_flag,
                            value_for_user_without_override,
                            override,
                            hasVariants,
                            currentValue,
                        }) => {
                            return (
                                <div className={'feature-flag-row'}>
                                    <Row
                                        className={
                                            override ? 'feature-flag-row-header overridden' : 'feature-flag-row-header'
                                        }
                                    >
                                        <Typography.Text ellipsis className="feature-flag-title">
                                            {feature_flag.key}
                                        </Typography.Text>
                                        <a
                                            className="feature-flag-external-link"
                                            href={`${apiURL}${
                                                feature_flag.id
                                                    ? urls.featureFlag(feature_flag.id)
                                                    : urls.featureFlags()
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

                                    <AnimatedCollapsible collapsed={!hasVariants || !currentValue}>
                                        <Row
                                            className={
                                                override ? 'variant-radio-group overridden' : 'variant-radio-group'
                                            }
                                        >
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
                </>
            )}
        </div>
    )
}
