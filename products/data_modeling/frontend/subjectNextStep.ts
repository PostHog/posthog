import { nodeEndpointModel } from './endpointModelName'
import type { AttentionSubject } from './modelsOverviewLogic'
import { REFRESH_LABELS, nextStepLabel } from './overviewIssueCopy'
import { subjectHref } from './subjectHref'

export type SubjectNextStep =
    | { kind: 'refresh'; savedQueryId: string; label: string }
    | { kind: 'link'; href: string; label: string }

export function subjectNextStep(subject: AttentionSubject): SubjectNextStep | null {
    const { node, materialization } = subject
    const problem = materialization?.kind
    if (node?.saved_query_id && !nodeEndpointModel(node) && (problem === 'failed' || problem === 'behind')) {
        return { kind: 'refresh', savedQueryId: node.saved_query_id, label: REFRESH_LABELS[problem] }
    }
    const href = subjectHref(subject)
    return href ? { kind: 'link', href, label: nextStepLabel(subject) } : null
}
