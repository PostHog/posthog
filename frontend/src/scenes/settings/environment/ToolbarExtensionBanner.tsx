import posthog from 'posthog-js'

import * as cursorPng from '@posthog/brand/hoggies/png/cursor'

import { pngHoggie } from 'lib/brand/hoggies'
import { TOOLBAR_CHROME_EXTENSION_URL } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

const HedgehogCursor = pngHoggie(cursorPng)

/** Points people who launch the toolbar from the authorized URLs at the Chrome extension, which needs no launch. */
export function ToolbarExtensionBanner(): JSX.Element {
    return (
        <LemonBanner
            type="info"
            icon={<HedgehogCursor className="size-12 shrink-0" />}
            dismissKey="toolbar-extension-authorized-urls"
            action={{
                children: 'Add to Chrome',
                to: TOOLBAR_CHROME_EXTENSION_URL,
                targetBlank: true,
                onClick: () => posthog.capture('toolbar extension banner clicked', { location: 'authorized urls' }),
                'data-attr': 'toolbar-extension-install',
            }}
        >
            <strong>Use the Chrome extension instead.</strong> It opens the toolbar in a side panel next to your
            website, on any of these URLs, so you don't need to launch it from here.
        </LemonBanner>
    )
}
