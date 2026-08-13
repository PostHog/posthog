import { MARKDOWN_BASE_EDITABLE_EXTENSIONS } from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { createTiptapMarkdownConverter } from 'lib/utils/markdown'

// No Image extension: definitions render with `disableImages` and agents consume the raw
// markdown, so an uploaded image would have no surface anywhere downstream.
export const METRIC_MARKDOWN_EXTENSIONS = [...MARKDOWN_BASE_EDITABLE_EXTENSIONS]

export const metricMarkdownConverter = createTiptapMarkdownConverter(METRIC_MARKDOWN_EXTENSIONS)
