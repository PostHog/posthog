import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ContentWidget } from '../../dashboard/dashboardTypes'
import type { MarkdownConfig } from './markdownSpec'

export function MarkdownWidget({ widget }: { widget: ContentWidget<MarkdownConfig> }): JSX.Element {
    // Every viewer would load an image from any URL the editor typed, so only PostHog-hosted images show.
    return (
        <LemonMarkdown className="TileGrid__text text-sm" disableImages>
            {widget.config.text}
        </LemonMarkdown>
    )
}
