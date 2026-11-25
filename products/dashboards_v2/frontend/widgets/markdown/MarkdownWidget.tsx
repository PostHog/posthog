// TODO(2026-11-25): Replace with quill once it can; quill has no markdown renderer yet.
// oxlint-disable-next-line no-restricted-imports
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
