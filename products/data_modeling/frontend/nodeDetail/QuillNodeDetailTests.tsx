import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'
import { QuillCheckCallout } from 'products/data_quality/frontend/QuillCheckCallout'

import type { NodeDetailDataQualitySubject } from './nodeDetailSceneLogic'
import { nodeDetailSceneLogic } from './nodeDetailSceneLogic'
import { QuillNodeDetailTableTests } from './QuillNodeDetailTableTests'
import { QuillNodeDetailViewTests } from './QuillNodeDetailViewTests'

function ResolvedTests({ id, subject }: { id: string; subject: NodeDetailDataQualitySubject }): JSX.Element {
    const { accessDenied } = useValues(
        dataQualityChecksLogic({ subjectType: subject.subjectType, subjectId: subject.subjectId })
    )

    if (accessDenied) {
        return (
            <Text size="xs" variant="muted" className="m-0">
                You don't have access to the tests for this model.
            </Text>
        )
    }

    if (subject.subjectType === 'view') {
        return <QuillNodeDetailViewTests id={id} subjectId={subject.subjectId} />
    }

    if (subject.subjectType === 'table' || subject.subjectType === 'posthog_table') {
        return (
            <QuillNodeDetailTableTests
                id={id}
                subjectType={subject.subjectType}
                subjectId={subject.subjectId}
                columns={subject.columns}
                editable={subject.editable}
            />
        )
    }

    return <QuillCheckCallout tone="info">Data quality is not available for this model.</QuillCheckCallout>
}

export function QuillNodeDetailTests({ id }: { id: string }): JSX.Element {
    const logic = nodeDetailSceneLogic({ id })
    const { node, dataQualitySubject, postHogSubjectLoading, postHogSubjectError, postHogSubjectAccessDenied } =
        useValues(logic)
    const { loadPostHogSubject } = useActions(logic)

    if (node?.type === 'table' && node.origin === 'posthog') {
        if (postHogSubjectLoading) {
            return (
                <QuillCheckCallout tone="info" busy>
                    Loading data quality for this table.
                </QuillCheckCallout>
            )
        }
        if (postHogSubjectAccessDenied) {
            return (
                <QuillCheckCallout tone="destructive">
                    You don't have access to data quality for this table. Ask a project admin for access.
                </QuillCheckCallout>
            )
        }
        if (postHogSubjectError) {
            return (
                <QuillCheckCallout tone="destructive" action={{ label: 'Retry', onClick: loadPostHogSubject }}>
                    Couldn't load data quality for this table. Try again.
                </QuillCheckCallout>
            )
        }
        if (!dataQualitySubject || dataQualitySubject.subjectType !== 'posthog_table') {
            return <QuillCheckCallout tone="info">Data quality is not available for this table.</QuillCheckCallout>
        }
    }

    if (!dataQualitySubject) {
        return <QuillCheckCallout tone="info">Data quality is not available for this model.</QuillCheckCallout>
    }

    return <ResolvedTests id={id} subject={dataQualitySubject} />
}
