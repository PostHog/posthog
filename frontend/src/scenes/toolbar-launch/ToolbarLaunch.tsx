import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { appUrlsLogic, KeyedAppUrl } from 'lib/components/AppEditorLink/appUrlsLogic'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import {
    PlusOutlined,
    EllipsisOutlined,
    DeleteOutlined,
    EditOutlined,
    CheckCircleFilled,
    SearchOutlined,
} from '@ant-design/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { Popup } from 'lib/components/Popup/Popup'
import { appEditorUrl } from 'lib/components/AppEditorLink/utils'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { IconFlag, IconGroupedEvents, IconHeatmap } from 'lib/components/icons'
import { Col, Row } from 'antd'

export const scene: SceneExport = {
    component: ToolbarLaunch,
}

function ToolbarLaunch(): JSX.Element {
    const { appUrlsKeyed, popoverOpen, suggestionsLoading } = useValues(appUrlsLogic)
    const { addUrl, setPopoverOpen, removeUrl } = useActions(appUrlsLogic)

    const features: FeatureHighlightProps[] = [
        {
            title: 'Heatmaps',
            caption: 'Understand where your users interact the most.',
            icon: <IconHeatmap />,
        },
        {
            title: 'Actions',
            caption: 'Create actions visually from elements in your website.',
            icon: <IconGroupedEvents />,
        },
        {
            title: 'Feature Flags',
            caption: 'Toggle feature flags on/off right on your app.',
            icon: <IconFlag />,
        },
        {
            title: 'Inspect',
            caption: 'Inspect clickable elements on your website.',
            icon: <SearchOutlined />,
        },
    ]

    const columns: LemonTableColumns<KeyedAppUrl> = [
        {
            title: 'URLs',
            dataIndex: 'url',
            key: 'url',
            render: function Render(url, record) {
                return (
                    <div className={clsx('authorized-url-col', record.type)}>
                        {record.type === 'authorized' && <CheckCircleFilled style={{ marginRight: 4 }} />}
                        {url}
                        {record.type === 'suggestion' && <LemonTag>Suggestion</LemonTag>}
                    </div>
                )
            },
        },
        {
            title: '',
            key: 'actions',
            render: function Render(_, record, index) {
                return (
                    <div className="actions-col">
                        {record.type === 'suggestion' ? (
                            <LemonButton type="default" onClick={() => addUrl(record.url)}>
                                <PlusOutlined /> Add as authorized
                            </LemonButton>
                        ) : (
                            <>
                                <a href={appEditorUrl(record.url, undefined, 'inspect')}>
                                    <LemonButton type="highlighted">Launch toolbar</LemonButton>
                                </a>
                                <Popup
                                    visible={popoverOpen === `${index}_${record.url}`}
                                    actionable
                                    onClickOutside={() => setPopoverOpen(null)}
                                    overlay={
                                        <>
                                            <LemonButton fullWidth type="stealth">
                                                <EditOutlined style={{ marginRight: 4 }} /> Edit authorized URL
                                            </LemonButton>
                                            <LemonButton
                                                fullWidth
                                                style={{ color: 'var(--danger)' }}
                                                type="stealth"
                                                onClick={() => removeUrl(index)}
                                            >
                                                <DeleteOutlined style={{ marginRight: 4 }} />
                                                Remove authorized URL
                                            </LemonButton>
                                        </>
                                    }
                                >
                                    <LemonButton
                                        type="stealth"
                                        onClick={() => setPopoverOpen(popoverOpen ? null : `${index}_${record.url}`)}
                                        style={{ marginLeft: 8 }}
                                    >
                                        <EllipsisOutlined
                                            style={{ color: 'var(--primary)', fontSize: 24 }}
                                            className="urls-dropdown-actions"
                                        />
                                    </LemonButton>
                                </Popup>
                            </>
                        )}
                    </div>
                )
            },
        },
    ]

    return (
        <div className="toolbar-launch-page">
            <PageHeader title="Toolbar" caption="The toolbar launches PostHog right in your app or website." />

            <LemonTable
                className="authorized-urls-table"
                columns={columns}
                dataSource={appUrlsKeyed}
                emptyState="There are no authorized URLs or domains. Add one to get started."
                loading={suggestionsLoading}
            />

            <div className="footer-caption">
                Make sure you're using the <Link to={`${urls.projectSettings()}#snippet`}>snippet</Link> or the latest{' '}
                <code>posthog-js</code> version.
            </div>

            <Row className="feature-highlight-list">
                {features.map((feature) => (
                    <FeatureHighlight key={feature.title} {...feature} />
                ))}
            </Row>
        </div>
    )
}

interface FeatureHighlightProps {
    title: string
    caption: string
    icon: JSX.Element
}

function FeatureHighlight({ title, caption, icon }: FeatureHighlightProps): JSX.Element {
    return (
        <Col sm={12} className="fh-item">
            <div className="fh-icon">{icon}</div>
            <div>
                <h4>{title}</h4>
                <div className="caption">{caption}</div>
            </div>
        </Col>
    )
}
