import { LemonTag } from '@posthog/lemon-ui'

import { KnowledgeSource } from '../scenes/businessKnowledgeLogic'

export function StatusTag({ status }: { status: KnowledgeSource['status'] }): JSX.Element {
    const variant =
        status === 'ready' ? 'success' : status === 'error' ? 'danger' : status === 'processing' ? 'warning' : 'muted'
    return <LemonTag type={variant}>{status}</LemonTag>
}
