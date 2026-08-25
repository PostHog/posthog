import { IconEyeHidden } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'

import type { RedactedMediaKind } from '../mediaSource'

const LARGE_EVENTS_DOCS_URL = 'https://posthog.com/docs/ai-observability/large-events'

const KIND_LABELS: Record<RedactedMediaKind, string> = {
    image: 'Image',
    file: 'File',
    audio: 'Audio',
}

export interface RedactedMediaPlaceholderProps {
    kind: RedactedMediaKind
    filename?: string
}

export function RedactedMediaPlaceholder({ kind, filename }: RedactedMediaPlaceholderProps): JSX.Element {
    return (
        <div
            className="flex items-start gap-2 p-2 text-xs text-muted bg-bg-light rounded border"
            data-attr="ai-message-redacted-media"
        >
            <IconEyeHidden className="shrink-0 mt-0.5 text-base" />
            <div>
                <div className="font-semibold">{KIND_LABELS[kind]} not captured.</div>
                <div>
                    PostHog redacts base64 media by default. Capturing it in full is in beta.{' '}
                    <Link to={LARGE_EVENTS_DOCS_URL} target="_blank">
                        Learn more about large events
                    </Link>
                </div>
                {filename && <div className="mt-1 font-mono">{filename}</div>}
            </div>
        </div>
    )
}
