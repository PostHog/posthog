import type { Meta, StoryObj } from '@storybook/react'

import { AccessControlLevel, DashboardType, QueryBasedInsightModel } from '~/types'

import { ImageTileModal } from 'products/dashboards/frontend/components/ImageTile/ImageTileModal'

const IMAGE_URL = 'https://imagedelivery.net/lvc9lblm6_VvsB0sE7lLrg/70-s-dance-hog/md'

const makeDashboard = (body?: string): DashboardType<QueryBasedInsightModel> =>
    ({
        id: 123,
        name: 'Image tile story',
        description: '',
        pinned: false,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        last_accessed_at: null,
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        tiles: body
            ? [
                  {
                      id: 1,
                      color: null,
                      layouts: {},
                      text: { body, last_modified_at: '2024-01-01T00:00:00Z' },
                  },
              ]
            : [],
        filters: {},
        tags: [],
        user_access_level: AccessControlLevel.Editor,
    }) as DashboardType<QueryBasedInsightModel>

const meta: Meta<typeof ImageTileModal> = {
    title: 'Products/Dashboards/Tiles/Image Tile Modal',
    component: ImageTileModal,
    parameters: {
        layout: 'fullscreen',
    },
    args: {
        isOpen: true,
        onClose: () => undefined,
        dashboard: makeDashboard(),
        imageTileId: null,
    },
}

export default meta
type Story = StoryObj<typeof ImageTileModal>

export const Empty: Story = {}

export const ExistingImage: Story = {
    args: {
        dashboard: makeDashboard(`![Portrait](${IMAGE_URL})`),
        imageTileId: 1,
    },
}

export const ExistingCover: Story = {
    args: {
        dashboard: makeDashboard(
            `<img src="${IMAGE_URL}" alt="Cover" data-layout="cover" data-position-x="75" data-position-y="50" />`
        ),
        imageTileId: 1,
    },
}
