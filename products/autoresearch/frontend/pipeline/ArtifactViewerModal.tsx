import { useActions, useValues } from 'kea'

import { LemonModal, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { humanizeBytes } from 'lib/utils/numbers'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

function languageForArtifact(path: string): Language {
    const lower = path.toLowerCase()
    if (lower.endsWith('.py')) {
        return Language.Python
    }
    if (lower.endsWith('.sql')) {
        return Language.SQL
    }
    if (lower.endsWith('.yml') || lower.endsWith('.yaml')) {
        return Language.YAML
    }
    if (lower.endsWith('.json') || lower.endsWith('.ipynb')) {
        return Language.JSON
    }
    return Language.Text
}

export function ArtifactViewerModal(): JSX.Element {
    const { viewedArtifact, viewedArtifactLoading } = useValues(autoresearchPipelineLogic)
    const { closeArtifact } = useActions(autoresearchPipelineLogic)
    return (
        <LemonModal
            isOpen={viewedArtifactLoading || viewedArtifact !== null}
            onClose={closeArtifact}
            title={viewedArtifact?.path ?? 'Artifact'}
            description={
                viewedArtifact
                    ? `${humanizeBytes(viewedArtifact.sizeBytes)} · run ${viewedArtifact.runId.slice(0, 8)}`
                    : undefined
            }
            width={960}
        >
            {viewedArtifactLoading ? (
                <Spinner />
            ) : viewedArtifact?.text != null ? (
                <CodeSnippet language={languageForArtifact(viewedArtifact.path)} wrap maxLinesWithoutExpansion={40}>
                    {viewedArtifact.text}
                </CodeSnippet>
            ) : (
                <div className="text-muted text-sm">
                    Binary file ({viewedArtifact ? humanizeBytes(viewedArtifact.sizeBytes) : ''}). No preview available.
                </div>
            )}
        </LemonModal>
    )
}
