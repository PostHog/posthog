import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { SearchOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { urls } from 'scenes/urls'
import { IconFlag, IconGroupedEvents, IconHeatmap } from 'lib/components/icons'
import { AuthorizedUrls } from './AuthorizedUrls'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: ToolbarLaunch,
}

function ToolbarLaunch(): JSX.Element {
    const { user, userLoading } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)

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
            <LemonDivider />

            <LemonSwitch
                data-tooltip="toolbar-authorized-toggle"
                label="Enable the PostHog toolbar"
                onChange={() =>
                    updateUser({
                        toolbar_mode: user?.toolbar_mode === 'disabled' ? 'toolbar' : 'disabled',
                    })
                }
                checked={user?.toolbar_mode !== 'disabled'}
                disabled={userLoading}
                loading={userLoading}
                type="primary"
                className="EnableToolbarSwitch mt mb pt pb full-width"
            />

            <h2 className="subtitle" id="urls">
                Authorized URLs for Toolbar
            </h2>
            <p>
                These are the domains and URLs where the <Link to={urls.toolbarLaunch()}>Toolbar</Link> will
                automatically launch if you're signed in to your PostHog account.
            </p>
            <AuthorizedUrls pageKey="toolbar-launch" />

            <div className="footer-caption text-muted mt text-center">
                Make sure you're using the <Link to={`${urls.projectSettings()}#snippet`}>HTML snippet</Link> or the
                latest <code>posthog-js</code> version.
            </div>

            <div className="feature-highlight-list mt-2 mx-auto mb-0 flex flex-wrap flex-center justify-center">
                {features.map((feature) => (
                    <FeatureHighlight key={feature.title} {...feature} />
                ))}
            </div>
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
        <div className="fh-item flex flex-center mt">
            <div className="fh-icon mr text-muted-alt">{icon}</div>
            <div>
                <h4 className="mb-0 text-muted-alt">{title}</h4>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}
