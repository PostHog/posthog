import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { SearchOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { IconFlag, IconGroupedEvents, IconHeatmap } from 'lib/components/icons'
import { Col, Row } from 'antd'
import { AuthorizedUrlsTable } from './AuthorizedUrlsTable'

export const scene: SceneExport = {
    component: ToolbarLaunch,
}

function ToolbarLaunch(): JSX.Element {
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

    return (
        <div className="toolbar-launch-page">
            <PageHeader title="Toolbar" caption="The toolbar launches PostHog right in your app or website." />

            <AuthorizedUrlsTable pageKey="toolbar-launch" />

            <div className="footer-caption">
                Make sure you're using the <Link to={`${urls.projectSettings()}#snippet`}>HTML snippet</Link> or the
                latest <code>posthog-js</code> version.
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
