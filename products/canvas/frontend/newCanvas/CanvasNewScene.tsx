import { IconPalette } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Text,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CanvasToolbar } from '../scene/CanvasToolbar'

export const scene: SceneExport = {
    component: CanvasNewScene,
}

/** Where old links to the start page land. Canvases are made with the PostHog MCP server, so this says how. */
export function CanvasNewScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')

    if (!enabled) {
        return <NotFound object="page" />
    }
    return (
        <div data-quill className="flex h-full min-h-0 flex-col bg-background">
            <CanvasToolbar dataAttr="canvas-new-toolbar">
                <Text size="sm" weight="medium" className="truncate pl-2">
                    New canvas
                </Text>
            </CanvasToolbar>
            <main className="min-h-0 flex-1">
                <Empty className="h-full border-0">
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconPalette />
                        </EmptyMedia>
                        <EmptyTitle>Canvases are made with the PostHog MCP server</EmptyTitle>
                        <EmptyDescription>
                            Ask your agent to build one. It appears in your canvases list when it's ready.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <div className="flex flex-wrap justify-center gap-2">
                            <Button
                                variant="outline"
                                render={
                                    <LinkPrimitive
                                        to="https://posthog.com/docs/model-context-protocol"
                                        target="_blank"
                                    />
                                }
                                data-attr="canvas-new-mcp-docs"
                            >
                                Set up the MCP server
                            </Button>
                            <Button
                                variant="outline"
                                render={<LinkPrimitive to={urls.canvases()} />}
                                data-attr="canvas-new-back-to-list"
                            >
                                Back to canvases
                            </Button>
                        </div>
                    </EmptyContent>
                </Empty>
            </main>
        </div>
    )
}
