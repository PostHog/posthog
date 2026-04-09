import { action } from '@storybook/addon-actions'
import { Meta, StoryObj } from '@storybook/react'

import type { DashboardTemplateItemProps } from './DashboardTemplateItem'
import { TemplateItem } from './DashboardTemplateItem'

const sampleTemplate: DashboardTemplateItemProps['template'] = {
    template_name: 'Weekly KPIs',
    dashboard_description: 'Track signups, retention, and revenue in one place.',
    image_url: undefined,
    tags: ['growth', 'product'],
}

function DashboardTemplateItemGallery(): JSX.Element {
    const onClick = action('onClick')

    return (
        <div className="flex max-w-3xl flex-col gap-10">
            <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Poster default (gradient fallback)</h3>
                <div className="w-72">
                    <TemplateItem
                        template={sampleTemplate}
                        onClick={onClick}
                        index={0}
                        data-attr="story-template-item-poster-fallback"
                        size="default"
                        showCover
                    />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Poster with image</h3>
                <div className="w-72">
                    <TemplateItem
                        template={{
                            ...sampleTemplate,
                            image_url: 'https://picsum.photos/seed/posthog-dashboard-template/400/240',
                        }}
                        onClick={onClick}
                        index={1}
                        data-attr="story-template-item-poster-image"
                        size="default"
                        showCover
                    />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Team row (no cover, default)</h3>
                <div className="w-72">
                    <TemplateItem
                        template={sampleTemplate}
                        onClick={onClick}
                        index={2}
                        data-attr="story-template-item-team-default"
                        size="default"
                        showCover={false}
                    />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Team row (no cover, large)</h3>
                <div className="max-w-lg">
                    <TemplateItem
                        template={sampleTemplate}
                        onClick={onClick}
                        index={3}
                        data-attr="story-template-item-team-large"
                        size="large"
                        showCover={false}
                    />
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold m-0">Featured large with heart</h3>
                <div className="w-full max-w-xl">
                    <TemplateItem
                        template={{
                            template_name: 'Starter pack',
                            dashboard_description:
                                'Horizontal layout with image column used in featured template choosers.',
                            image_url: 'https://picsum.photos/seed/posthog-featured-template/400/240',
                            tags: ['product', 'onboarding'],
                        }}
                        onClick={onClick}
                        index={4}
                        data-attr="story-template-item-featured"
                        size="large"
                        showCover
                        showFavourite
                    />
                </div>
            </section>
        </div>
    )
}

const meta: Meta<typeof DashboardTemplateItemGallery> = {
    title: 'Scenes-App/Dashboards/Templates/Dashboard template item',
    component: DashboardTemplateItemGallery,
    decorators: [
        (Story) => (
            <div className="bg-primary min-h-screen w-full p-8">
                <Story />
            </div>
        ),
    ],
    parameters: {
        posthogTheme: 'light',
        backgrounds: { default: 'light' },
        layout: 'fullscreen',
    },
}

export default meta

type Story = StoryObj<typeof DashboardTemplateItemGallery>

export const AllVersions: Story = {
    render: () => <DashboardTemplateItemGallery />,
}
