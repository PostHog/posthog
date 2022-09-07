import { LemonTable } from '@posthog/lemon-ui'
import Link from 'antd/lib/typography/Link'
import { useValues } from 'kea'
import { LemonTableColumns } from 'lib/components/LemonTable'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import React from 'react'
import { urls } from 'scenes/urls'
import { FeatureFlagType } from '~/types'
import { relatedFeatureFlagsLogic } from './relatedFeatureFlagsLogic'

export interface RelatedFeatureFlagType extends FeatureFlagType {
    value: boolean | string
    evaluation: FeatureFlagEvaluationType
}

interface FeatureFlagEvaluationType {
    reason: string
    condition_index?: number
}

interface Props {
    distinctId: string
}

export function RelatedFeatureFlags({ distinctId }: Props): JSX.Element {
    const { relatedFeatureFlags } = useValues(relatedFeatureFlagsLogic({ distinctId }))

    const columns: LemonTableColumns<RelatedFeatureFlagType> = [
        {
            title: normalizeColumnTitle('Key'),
            dataIndex: 'key',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            sorter: (a: RelatedFeatureFlagType, b: RelatedFeatureFlagType) => (a.key || '').localeCompare(b.key || ''),
            render: function Render(_, featureFlag: RelatedFeatureFlagType) {
                return (
                    <>
                        <Link to={featureFlag.id ? urls.featureFlag(featureFlag.id) : undefined} className="row-name">
                            {stringWithWBR(featureFlag.key, 17)}
                        </Link>
                        {featureFlag.name && <span className="row-description">{featureFlag.name}</span>}
                    </>
                )
            },
        },
        {
            title: 'Type',
            width: 100,
            render: function Render(_, featureFlag: RelatedFeatureFlagType) {
                // TODO : determine type
                return featureFlag ? 'Release toggle' : 'Multiple variants'
            },
        },
        {
            title: 'Value',
            dataIndex: 'value',
            width: 100,
            render: function Render(_, featureFlag: RelatedFeatureFlagType) {
                return <div>{featureFlag.value}</div>
            },
        },
        {
            title: 'Evaluation Reason',
            dataIndex: 'evaluation',
            width: 150,
            render: function Render(_, featureFlag: RelatedFeatureFlagType) {
                return <div>{featureFlag.evaluation.reason}</div>
            },
        },
        {
            title: 'Status',
            dataIndex: 'active',
            sorter: (a: RelatedFeatureFlagType, b: RelatedFeatureFlagType) => Number(a.active) - Number(b.active),
            width: 100,
            render: function RenderActive(_, featureFlag: RelatedFeatureFlagType) {
                return <span className="font-normal">{featureFlag.active ? 'Enabled' : 'Disabled'}</span>
            },
        },
    ]
    return (
        <>
            <LemonTable columns={columns} dataSource={relatedFeatureFlags} />
        </>
    )
}
