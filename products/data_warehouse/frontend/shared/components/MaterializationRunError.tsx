import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { DataModelingJobStatus } from '~/types'

interface MaterializationRunErrorProps {
    error: string | null
    status: DataModelingJobStatus
}

interface RunErrorPresentation {
    title: string
    copyNoun: string
    textClass: string
}

const PRESENTATION_BY_STATUS: Record<DataModelingJobStatus, RunErrorPresentation> = {
    Failed: { title: 'Run error', copyNoun: 'error', textClass: 'text-danger' },
    Completed: { title: 'Run warning', copyNoun: 'warning', textClass: 'text-secondary' },
    Skipped: { title: 'Skip reason', copyNoun: 'skip reason', textClass: 'text-secondary' },
    Cancelled: { title: 'Cancellation reason', copyNoun: 'cancellation reason', textClass: 'text-secondary' },
    Running: { title: 'Run message', copyNoun: 'message', textClass: 'text-secondary' },
}

export function MaterializationRunError({ error, status }: MaterializationRunErrorProps): JSX.Element | null {
    if (!error) {
        return null
    }
    const presentation = PRESENTATION_BY_STATUS[status]
    return (
        <div className="mb-4 min-w-0" data-attr="materialization-run-error">
            <h4 className={presentation.textClass}>{presentation.title}</h4>
            <CodeSnippet
                language={Language.Text}
                wrap
                compact
                thing={presentation.copyNoun}
                className="[&_pre]:max-h-64 [&_pre]:overflow-auto"
            >
                {error}
            </CodeSnippet>
        </div>
    )
}
