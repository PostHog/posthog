import type { Meta, StoryObj } from '@storybook/react'

import { IconBrowser, IconStore } from '@posthog/icons'

import { getTreeItemsProducts } from '~/products'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { OsAppIcon } from './OsAppIcon'

const meta: Meta = {
    title: 'Scenes-App/OS/App icon',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<Record<string, never>>

export const EveryApp: Story = {
    render: () => (
        <div className="flex flex-col gap-6">
            <div className="flex items-end gap-4">
                <OsAppIcon app={null} icon={<IconStore />} color="var(--brand-red)" size="large" />
                <OsAppIcon app={null} icon={<IconBrowser />} size="large" />
                <OsAppIcon app={{ iconType: 'product_analytics' }} size="large" />
                <OsAppIcon app={{ iconType: 'product_analytics' }} size="medium" />
                <OsAppIcon app={{ iconType: 'product_analytics' }} size="small" />
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,4rem)] gap-4">
                {getTreeItemsProducts()
                    .filter((item) => item.href)
                    .map((item) => (
                        <OsAppIcon
                            key={item.path}
                            app={{
                                iconType: item.iconType ?? (item.type as FileSystemIconType | undefined),
                                iconColor: item.iconColor,
                            }}
                            size="large"
                        />
                    ))}
            </div>
        </div>
    ),
}
