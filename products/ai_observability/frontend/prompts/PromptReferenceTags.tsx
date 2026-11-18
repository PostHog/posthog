import { LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { extractPromptReferences } from './promptReferences'

export function PromptReferenceTags({ text }: { text: string }): JSX.Element | null {
    const references = extractPromptReferences(text)
    if (references.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-1">
            <span className="text-xs text-secondary">References:</span>
            {references.map((reference) => (
                <Link
                    key={reference.raw}
                    to={urls.aiObservabilityPrompt(reference.name)}
                    data-attr="llma-prompt-reference-tag"
                >
                    <LemonTag type="completion" size="small">
                        {reference.name} @ {reference.label ?? `v${reference.version}`}
                    </LemonTag>
                </Link>
            ))}
        </div>
    )
}
