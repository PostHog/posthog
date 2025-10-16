import './ToolbarLaunch.scss'

import { IconFlag, IconPieChart, IconSearch, IconTestTube, IconToolbar } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { IconGroupedEvents, IconHeatmap } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: ToolbarLaunch,
    settingSectionId: 'environment-details',
}

export function ToolbarLaunch(): JSX.Element {
    const isExperimentsEnabled = useFeatureFlag('WEB_EXPERIMENTS')

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
            icon: <IconSearch />,
        },
        {
            title: 'Web Vitals',
            caption: "Measure your website's performance.",
            icon: <IconPieChart />,
        },
        ...(isExperimentsEnabled
            ? [
                  {
                      title: 'Experiments',
                      caption: 'Run experiments and A/B test your website.',
                      icon: <IconTestTube />,
                  },
              ]
            : []),
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Toolbar"
                description="PostHog toolbar launches PostHog right in your app or website."
                resourceType={{
                    type: 'toolbar',
                    forceIcon: <IconToolbar />,
                }}
            />

            <SceneDivider />

            <SceneSection title="Authorized URLs for Toolbar" description="Click on the URL to launch the toolbar.">
                <AuthorizedUrlList type={AuthorizedUrlListType.TOOLBAR_URLS} addText="Add authorized URL" />
                <LemonBanner type="info">
                    Make sure you're using the <Link to={`${urls.settings('project')}#snippet`}>HTML snippet</Link> or
                    the latest <code>posthog-js</code> version.
                </LemonBanner>
            </SceneSection>

            <SceneSection>
                <div className="grid grid-cols-2 gap-4 max-w-[800px] mb-6 mt-4 mx-auto">
                    {features.map((feature) => (
                        <FeatureHighlight key={feature.title} {...feature} />
                    ))}
                </div>
            </SceneSection>
        </SceneContent>
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
            <div className="fh-icon mr-4 text-secondary">{icon}</div>
            <div>
                <h4 className="mb-0 text-secondary">{title}</h4>
                <div className="caption">{caption}</div>
            </div>
        </div>
    )
}
