import './ToolbarLaunch.scss'

import { IconFlag, IconFlask, IconPieChart, IconSearch } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconGroupedEvents, IconHeatmap } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

export const scene: SceneExport = {
    component: ToolbarLaunch,
    productKey: ProductKey.TOOLBAR,
}

export function ToolbarLaunch(): JSX.Element {
    // Authorized URLs are a single shared team field; the backend gates edits on web analytics
    // editor access, so only offer the add/edit/delete controls to users who can actually save.
    // In Storybook there's no app context, so allow editing there.
    const canEdit =
        inStorybook() || inStorybookTestRunner()
            ? true
            : userHasAccess(AccessControlResourceType.WebAnalytics, AccessControlLevel.Editor)

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
        {
            title: 'Experiments',
            caption: 'Run experiments and A/B test your website.',
            icon: <IconFlask />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Toolbar"
                description="PostHog toolbar launches PostHog right in your app or website."
                resourceType={{
                    type: 'toolbar',
                }}
            />

            <SceneSection title="Authorized URLs for Toolbar" description="Click on the URL to launch the toolbar.">
                <AuthorizedUrlList
                    type={AuthorizedUrlListType.TOOLBAR_URLS}
                    addText="Add authorized URL"
                    allowAdd={canEdit}
                    allowDelete={canEdit}
                    displaySuggestions={canEdit}
                />
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
