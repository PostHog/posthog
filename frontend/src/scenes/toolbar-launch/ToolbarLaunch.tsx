import {
    IconBolt,
    IconCursorClick,
    IconExternal,
    IconFlask,
    IconInfo,
    IconPieChart,
    IconSearch,
    IconToggle,
} from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Item,
    ItemContent,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Text,
    TooltipProvider,
} from '@posthog/quill'

import { userHasAccess } from 'lib/utils/accessControlUtils'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductIconWrapper } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ToolbarAuthorizedUrls } from './ToolbarAuthorizedUrls'

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

    const features: Array<{ title: string; caption: string; icon: JSX.Element; type: FileSystemIconType }> = [
        {
            title: 'Heatmaps',
            caption: 'Understand where your users interact the most.',
            icon: <IconCursorClick className="size-5" />,
            type: 'heatmap',
        },
        {
            title: 'Actions',
            caption: 'Create actions visually from elements in your website.',
            icon: <IconBolt className="size-5" />,
            type: 'action',
        },
        {
            title: 'Feature flags',
            caption: 'Override feature flags while you test your app.',
            icon: <IconToggle className="size-5" />,
            type: 'feature_flag',
        },
        {
            title: 'Inspect',
            caption: 'Inspect clickable elements on your website.',
            icon: <IconSearch className="size-5" />,
            type: 'product_analytics',
        },
        {
            title: 'Web vitals',
            caption: "Measure your website's performance.",
            icon: <IconPieChart className="size-5" />,
            type: 'web_analytics',
        },
        {
            title: 'Experiments',
            caption: 'Run experiments and A/B test your website.',
            icon: <IconFlask className="size-5" />,
            type: 'experiment',
        },
    ]

    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name="Toolbar"
                    description="Open PostHog on your website to inspect elements, review behavior, and test changes in context."
                    resourceType={{ type: 'toolbar' }}
                />

                <div className="@container/toolbar-launch mt-4 flex max-w-6xl flex-col gap-4">
                    <div className="grid grid-cols-1 gap-4 @min-[64rem]/toolbar-launch:grid-cols-3">
                        <Card className="min-w-0 @min-[64rem]/toolbar-launch:col-span-2">
                            <CardHeader>
                                <CardTitle>Authorized URLs</CardTitle>
                                <CardDescription>Add a URL, then launch the toolbar on that website.</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <ToolbarAuthorizedUrls canEdit={canEdit} />
                            </CardContent>
                        </Card>

                        <Card size="sm" className="group/colorful-product-icons colorful-product-icons-true">
                            <CardHeader>
                                <CardTitle>What you can do</CardTitle>
                                <CardDescription>Use the toolbar without leaving your website.</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <ItemGroup>
                                    {features.map((feature) => (
                                        <Item key={feature.title} size="xs">
                                            <ItemMedia variant="icon">
                                                <ProductIconWrapper type={feature.type}>
                                                    {feature.icon}
                                                </ProductIconWrapper>
                                            </ItemMedia>
                                            <ItemContent>
                                                <ItemTitle>{feature.title}</ItemTitle>
                                                <Text size="xs" variant="muted">
                                                    {feature.caption}
                                                </Text>
                                            </ItemContent>
                                        </Item>
                                    ))}
                                </ItemGroup>
                            </CardContent>
                        </Card>
                    </div>

                    <Card size="sm">
                        <CardContent className="flex flex-wrap items-center gap-2">
                            <IconInfo />
                            <Text size="sm" className="min-w-64 flex-1">
                                The toolbar requires the HTML snippet or a recent version of posthog-js.
                            </Text>
                            <Button
                                variant="link"
                                render={
                                    // eslint-disable-next-line react/forbid-elements
                                    <a href={`${urls.settings('project')}#snippet`} />
                                }
                            >
                                View installation settings
                                <IconExternal />
                            </Button>
                        </CardContent>
                    </Card>
                </div>
            </SceneContent>
        </TooltipProvider>
    )
}
