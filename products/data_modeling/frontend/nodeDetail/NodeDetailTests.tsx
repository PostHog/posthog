import { useActions, useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import type { DataQualitySubjectType } from 'products/data_quality/frontend/checksApi'
import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

import type { NodeDetailDataQualitySubject } from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { NodeDetailTableTests } from './NodeDetailTableTests'
import { NodeDetailViewTests } from './NodeDetailViewTests'

export type NodeDetailTestsSubjectType = DataQualitySubjectType

export function NodeDetailTests({ id }: { id: string }): JSX.Element {
    const logic = nodeDetailSceneLogic({ id })
    const { node, dataQualitySubject, postHogSubjectLoading, postHogSubjectError, postHogSubjectAccessDenied } =
        useValues(logic)
    const { loadPostHogSubject } = useActions(logic)

    if (node?.type === 'table' && node.origin === 'posthog') {
        if (postHogSubjectLoading) {
            return (
                <LemonBanner type="info" icon={<Spinner />}>
                    Loading data quality for this table.
                </LemonBanner>
            )
        }

        if (postHogSubjectAccessDenied) {
            return (
                <LemonBanner type="error">
                    You don't have access to data quality for this table. Ask a project admin for access.
                </LemonBanner>
            )
        }

        if (postHogSubjectError) {
            return (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadPostHogSubject }}>
                    Couldn't load data quality for this table. Try again.
                </LemonBanner>
            )
        }

        if (!dataQualitySubject || dataQualitySubject.subjectType !== 'posthog_table') {
            return <LemonBanner type="info">Data quality is not available for this table.</LemonBanner>
        }
    }

    if (!dataQualitySubject) {
        return <LemonBanner type="info">Data quality is not available for this model.</LemonBanner>
    }

    return <ResolvedNodeDetailTests id={id} subject={dataQualitySubject} />
}

function ResolvedNodeDetailTests({ id, subject }: { id: string; subject: NodeDetailDataQualitySubject }): JSX.Element {
    const { accessDenied } = useValues(
        dataQualityChecksLogic({ subjectType: subject.subjectType, subjectId: subject.subjectId })
    )

    if (accessDenied) {
        return <p className="mb-0 text-secondary">You don't have access to the tests for this model.</p>
    }

    if (subject.subjectType === 'view') {
        return <NodeDetailViewTests id={id} subjectId={subject.subjectId} />
    }

    if (subject.subjectType === 'table' || subject.subjectType === 'posthog_table') {
        return (
            <NodeDetailTableTests
                id={id}
                subjectType={subject.subjectType}
                subjectId={subject.subjectId}
                columns={subject.columns}
                editable={subject.editable}
            />
        )
    }

    return <LemonBanner type="info">Data quality is not available for this model.</LemonBanner>
}
