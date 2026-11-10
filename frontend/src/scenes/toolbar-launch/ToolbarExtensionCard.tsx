import { useValues } from 'kea'
import posthog from 'posthog-js'

import * as cursorPng from '@posthog/brand/hoggies/png/cursor'
import { IconExternal } from '@posthog/icons'
import { Button, Card, CardContent, Text } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { TOOLBAR_CHROME_EXTENSION_URL } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { toolbarExtensionLogic } from './toolbarExtensionLogic'

const HedgehogCursor = pngHoggie(cursorPng)

/** Points people at the Chrome extension, which opens the toolbar in a side panel without a launch from this page. */
export function ToolbarExtensionCard(): JSX.Element | null {
    const { extensionInstalled } = useValues(toolbarExtensionLogic)

    // Hidden until detection answers, so people who have the extension never see it flash.
    if (extensionInstalled !== false) {
        return null
    }

    return (
        <Card size="sm">
            <CardContent className="flex flex-wrap items-center gap-4">
                <HedgehogCursor className="size-16 shrink-0" />
                <div className="flex min-w-64 flex-1 flex-col gap-1">
                    <Text weight="semibold">Use the Chrome extension instead</Text>
                    <Text size="sm" variant="muted">
                        Opens the toolbar in a side panel next to your website, on any authorized URL.
                    </Text>
                </div>
                <Button
                    variant="primary"
                    render={<LinkPrimitive to={TOOLBAR_CHROME_EXTENSION_URL} target="_blank" />}
                    onClick={() => posthog.capture('toolbar extension banner clicked', { location: 'toolbar' })}
                    data-attr="toolbar-extension-install"
                >
                    <IconExternal />
                    Add to Chrome
                </Button>
            </CardContent>
        </Card>
    )
}
