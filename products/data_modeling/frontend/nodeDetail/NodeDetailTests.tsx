import { useValues } from 'kea'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

import { NodeDetailTableTests } from './NodeDetailTableTests'
import { NodeDetailViewTests } from './NodeDetailViewTests'

export type NodeDetailTestsSubjectType = 'table' | 'view'

export function NodeDetailTests({
    id,
    subjectType,
    subjectId,
}: {
    id: string
    subjectType: NodeDetailTestsSubjectType
    subjectId: string
}): JSX.Element {
    const { accessDenied } = useValues(dataQualityChecksLogic({ subjectType, subjectId }))

    if (accessDenied) {
        return <p className="mb-0 text-secondary">You don't have access to the tests for this model.</p>
    }

    return subjectType === 'view' ? (
        <NodeDetailViewTests id={id} subjectId={subjectId} />
    ) : (
        <NodeDetailTableTests id={id} subjectId={subjectId} />
    )
}
