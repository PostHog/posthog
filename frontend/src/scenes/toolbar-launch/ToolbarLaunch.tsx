import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import './ToolbarLaunch.scss'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { IconFlag, IconGroupedEvents, IconHeatmap, IconMagnifier } from 'lib/lemon-ui/icons'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

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
            icon: <IconMagnifier />,
        },
    ]

    return (
        <div className="toolbar-launch-page">
            <PageHeader title="Toolbar" caption="The toolbar launches PostHog right in your app or website." />
            <LemonDivider />

            <h2 className="subtitle" id="urls">
                Authorized URLs for Toolbar
            </h2>
            <p>
                Click on the URL to launch the toolbar.{' '}
                {window.location.host === 'app.posthog.com' && 'Remember to disable your adblocker.'}
            </p>
            <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} addText={'Add authorized URL'} />

            <div className="footer-caption text-muted mt-4 text-center">
                Make sure you're using the <Link to={`${urls.projectSettings()}#snippet`}>HTML snippet</Link> or the
                latest <code>posthog-js</code> version.
            </div>

            <div className="feature-highlight-list mt-8 mx-auto mb-0 flex flex-wrap items-center justify-center">
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
        <div className="fh-item flex items-center mt-4">
            <div className="fh-icon mr-4 text-muted-alt">{icon}</div>
            <div>
                <h4 className="mb-0 text-muted-alt">{title}</h4>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}
