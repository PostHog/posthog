import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { ContentWidget } from '../../dashboard/dashboardTypes'
import type { MarkdownConfig } from './markdownSpec'

export function MarkdownWidget({ widget }: { widget: ContentWidget<MarkdownConfig> }): JSX.Element {
    return <LemonMarkdown className="text-sm">{widget.config.text}</LemonMarkdown>
}
