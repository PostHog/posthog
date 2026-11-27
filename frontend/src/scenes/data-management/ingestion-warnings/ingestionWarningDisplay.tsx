import { IngestionWarning } from './ingestionWarningsLogic'
import {
    WARNING_TYPE_RENDERER,
    WARNING_TYPE_TO_DESCRIPTION,
    WARNING_TYPE_TO_DOCS_ANCHOR,
} from './ingestionWarningTypes'

export function warningTypeLabel(type: string): string {
    return WARNING_TYPE_TO_DESCRIPTION[type as keyof typeof WARNING_TYPE_TO_DESCRIPTION] || type
}

export function warningDocsUrl(type: string): string {
    const docsAnchor = WARNING_TYPE_TO_DOCS_ANCHOR[type]
    return docsAnchor
        ? `https://posthog.com/docs/data/ingestion-warnings#${docsAnchor}`
        : 'https://posthog.com/docs/data/ingestion-warnings'
}

export function renderWarningDescription(warning: IngestionWarning): JSX.Element {
    const renderer = WARNING_TYPE_RENDERER[warning.type as keyof typeof WARNING_TYPE_RENDERER]
    return renderer ? renderer(warning) : <pre>{JSON.stringify(warning.details, null, 2)}</pre>
}
