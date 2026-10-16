import { Meta, StoryFn } from '@storybook/react'

import { SourceCatalogSkeleton } from './SourceCatalogSkeleton'

const meta: Meta<typeof SourceCatalogSkeleton> = {
    title: 'Data Warehouse/SourceCatalogSkeleton',
    component: SourceCatalogSkeleton,
    parameters: {
        // The whole component is LemonSkeletons, which the snapshot runner treats as loaders and
        // waits out before it captures. Without this the story never settles.
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

export const Default: StoryFn<typeof SourceCatalogSkeleton> = () => <SourceCatalogSkeleton />

// The nav sidebar plus an open side panel leave about this much room for the scene.
export const NarrowScene: StoryFn<typeof SourceCatalogSkeleton> = () => (
    <div className="w-[520px]">
        <SourceCatalogSkeleton />
    </div>
)
