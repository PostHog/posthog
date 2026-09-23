import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useState } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { mswDecorator } from '~/mocks/browser'

import { osWindowsLogic } from '../windows/osWindowsLogic'
import { OsShell } from './OsShell'
import { osShellLogic } from './osShellLogic'
import { OsWallpaperKey } from './osWallpapers'

const MOCK_TOOLS = ['Product analytics', 'Web analytics', 'Session replay', 'Feature flags', 'Surveys'].map(
    (productPath, index) => ({
        id: `product-${index}`,
        product_path: productPath,
        enabled: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    })
)

/**
 * The desktop without a window. A story runs inside Storybook's own page, so the window it would
 * open for the current URL is closed before the shell renders.
 */
function OsDesktopStory({ wallpaper }: { wallpaper: OsWallpaperKey }): JSX.Element | null {
    const { setWallpaper } = useActions(osShellLogic)
    const { restoreLayout } = useActions(osWindowsLogic)
    const { loadCustomProducts } = useActions(customProductsLogic)
    const [ready, setReady] = useState(false)
    useOnMountEffect(() => {
        restoreLayout([])
        setWallpaper(wallpaper)
        loadCustomProducts()
        setReady(true)
    })
    return ready ? <OsShell /> : null
}

const meta: Meta<typeof OsDesktopStory> = {
    title: 'Scenes-App/OS shell',
    component: OsDesktopStory,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForSelector: '[data-attr="os-desktop-icon-tool-Surveys"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/user_product_list': () => [200, { results: MOCK_TOOLS }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof OsDesktopStory>

export const KeyboardGarden: Story = { args: { wallpaper: 'keyboard-garden' } }
export const Hogzilla: Story = { args: { wallpaper: 'hogzilla' } }
export const StartupMonopoly: Story = { args: { wallpaper: 'startup-monopoly' } }
export const OfficeParty: Story = { args: { wallpaper: 'office-party' } }
