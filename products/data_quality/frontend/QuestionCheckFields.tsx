import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'

import { dataQualityCheckEditorLogic } from './dataQualityCheckEditorLogic'
import type { QuestionPreviewInputApi } from './generated/api.schemas'

export function QuestionCheckFields(): JSX.Element {
    const {
        checkForm,
        availableColumns,
        currentQuestionPreview,
        questionPreviewLoading,
        questionPreviewError,
        questionPreviewDisabledReason,
        questionPreviewFailureRate,
        questionPreviewPassed,
    } = useValues(dataQualityCheckEditorLogic)
    const { setCheckFormValues, requestQuestionPreview } = useActions(dataQualityCheckEditorLogic)
    const preview = currentQuestionPreview
    const validThreshold =
        checkForm.minProbability !== null &&
        Number.isFinite(checkForm.minProbability) &&
        checkForm.minProbability >= 0 &&
        checkForm.minProbability <= 1

    return (
        <div className="flex flex-col gap-3 min-w-0">
            <div className="flex flex-wrap gap-2 items-center">
                <LemonTag type="muted">All rows in scope</LemonTag>
                <span className="text-secondary text-sm">
                    Full runs examine every row. Question checks are warning only.
                </span>
            </div>
            <LemonField name="questionInputMode" label="Evaluate">
                <LemonSelect
                    options={[
                        { value: 'column', label: 'One column' },
                        { value: 'row', label: 'Selected row fields' },
                    ]}
                    onChange={(questionInputMode) =>
                        setCheckFormValues({ questionInputMode, columnName: '', questionColumns: [] })
                    }
                />
            </LemonField>
            {checkForm.questionInputMode === 'column' ? (
                <LemonField name="columnName" label="Column" help="Null values fail without inference.">
                    <LemonSelect options={availableColumns.map((name) => ({ value: name, label: name }))} />
                </LemonField>
            ) : (
                <LemonField
                    name="questionColumns"
                    label="Row fields"
                    help="Only these fields are sent together, with their names, types, and null values."
                >
                    <LemonInputSelect
                        mode="multiple"
                        options={availableColumns.map((name) => ({ key: name, label: name }))}
                        placeholder="Select fields"
                        data-attr="data-quality-question-columns"
                    />
                </LemonField>
            )}
            <LemonField name="question" label="Question" help="Ask a yes/no question. Yes means the data is valid.">
                <LemonTextArea minRows={2} placeholder="Does this description explain what the item is used for?" />
            </LemonField>
            <div className="flex flex-wrap gap-3">
                <LemonField
                    name="minProbability"
                    label="Minimum probability of Yes"
                    className="flex-1 min-w-48"
                    help="From 0 to 1. A value equal to the threshold passes."
                >
                    <LemonInput type="number" min={0} max={1} step={0.05} />
                </LemonField>
                <LemonField
                    name="maxFailureRate"
                    label="Allowed failure rate"
                    className="flex-1 min-w-48"
                    help="From 0 to 1. A rate equal to the limit passes. 0 requires every row to pass."
                >
                    <LemonInput type="number" min={0} max={1} step={0.05} />
                </LemonField>
            </div>
            <div className="flex flex-col gap-2 border-t pt-3 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={requestQuestionPreview}
                        loading={questionPreviewLoading}
                        disabledReason={questionPreviewLoading ? 'Preview running' : questionPreviewDisabledReason}
                        data-attr="data-quality-question-preview"
                    >
                        Preview up to 10 rows
                    </LemonButton>
                    {preview && (
                        <LemonTag
                            type={
                                questionPreviewPassed === null ? 'muted' : questionPreviewPassed ? 'success' : 'warning'
                            }
                        >
                            {preview.examined_row_count === 0
                                ? 'No rows to preview'
                                : questionPreviewPassed === null
                                  ? 'Preview'
                                  : questionPreviewPassed
                                    ? 'Preview passed'
                                    : 'Preview failed'}
                        </LemonTag>
                    )}
                </div>
                <p className="text-secondary text-sm mb-0">
                    Preview checks a small subset and does not save a run. New inputs use AI credits. Cached decisions
                    are reused; decision counts are not billing totals.
                </p>
                {questionPreviewError && <LemonBanner type="error">{questionPreviewError}</LemonBanner>}
                {preview && (
                    <>
                        <p className="mb-0 text-sm" data-attr="data-quality-question-preview-summary">
                            {/* Each changing part is one element with one text child. Page translation
                                swaps bare text nodes for <font> elements, so React's updates would go stale
                                and removing the failure rate would throw NotFoundError (react#11538). */}
                            <span>{`${pluralize(preview.examined_row_count, 'row')} previewed. `}</span>
                            <span>
                                {`${pluralize(preview.reused_decision_count, 'decision')} reused, ${preview.new_decision_count} new.`}
                            </span>
                            {questionPreviewFailureRate !== null && (
                                <span>{` ${(questionPreviewFailureRate * 100).toFixed(1)}% failed.`}</span>
                            )}
                        </p>
                        <LemonTable<QuestionPreviewInputApi>
                            size="small"
                            dataSource={preview.inputs}
                            rowKey={(item) => item.input ?? '__null'}
                            emptyState="This table has no rows to preview."
                            columns={[
                                {
                                    title: 'Input',
                                    key: 'input',
                                    render: (_, item) => (
                                        <span className="whitespace-pre-wrap break-all">
                                            {item.input === null ? 'NULL' : item.input || '(empty string)'}
                                        </span>
                                    ),
                                },
                                { title: 'Rows', dataIndex: 'row_count' },
                                {
                                    title: 'Probability of Yes',
                                    key: 'probability',
                                    render: (_, item) =>
                                        item.probability === null
                                            ? 'No inference'
                                            : `${(item.probability * 100).toFixed(1)}%`,
                                },
                                {
                                    title: 'Result',
                                    key: 'result',
                                    render: (_, item) => (
                                        <LemonTag
                                            type={
                                                !validThreshold
                                                    ? 'muted'
                                                    : item.probability !== null &&
                                                        item.probability >= checkForm.minProbability!
                                                      ? 'success'
                                                      : 'warning'
                                            }
                                        >
                                            {!validThreshold
                                                ? 'Set threshold'
                                                : item.probability !== null &&
                                                    item.probability >= checkForm.minProbability!
                                                  ? 'Pass'
                                                  : 'Fail'}
                                        </LemonTag>
                                    ),
                                },
                            ]}
                        />
                    </>
                )}
            </div>
        </div>
    )
}
