import { Link } from '@posthog/lemon-ui'

interface DocumentationLinkProps {
    provider?: string
    path?: string
    text?: string
}

export function DocumentationLink({
    provider,
    path,
    text = 'View full documentation →',
}: DocumentationLinkProps): JSX.Element {
    const url = path
        ? `https://posthog.com/docs/${path}`
        : `https://posthog.com/docs/llm-analytics/installation/${provider}`

    return (
        <p className="mt-4">
            <Link to={url} target="_blank">
                {text}
            </Link>
        </p>
    )
}
