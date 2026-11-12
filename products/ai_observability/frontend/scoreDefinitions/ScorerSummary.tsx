import type { ReactNode } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { CodeLine, Language } from 'lib/components/CodeSnippet'

import { formatCompositeExpression } from './formatCompositeExpression'
import { formatKindLabel, getScoreDefinitionOptionKey, type ScoreDefinitionDraft } from './scoreDefinitionModalUtils'

export function ScorerSummary({
    draft,
    heading = 'Preview',
    inputSummary,
}: {
    draft: ScoreDefinitionDraft
    heading?: string
    inputSummary?: ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-4">
            <div>
                <h3 className="mb-3">{heading}</h3>
                <div className="font-semibold break-words">{draft.shortName || draft.name || 'New scorer'}</div>
                <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-sm mt-3 mb-0">
                    <dt className="text-muted">Output</dt>
                    <dd className="m-0">{formatKindLabel(draft.kind)}</dd>
                    <dt className="text-muted">Calculation</dt>
                    <dd className="m-0">
                        {draft.calculation === 'composite' ? (
                            <LemonTag type="info">Composite</LemonTag>
                        ) : (
                            'Reported score'
                        )}
                    </dd>
                </dl>
            </div>
            {draft.kind === 'numeric' ? (
                <div className="flex flex-col gap-2">
                    <h4 className="mb-0">Possible values</h4>
                    <div className="text-sm text-muted">
                        {draft.numericMin || draft.numericMax
                            ? `${draft.numericMin || 'No minimum'} to ${draft.numericMax || 'no maximum'}`
                            : 'Any number'}
                    </div>
                    {draft.calculation === 'reported' && draft.numericStep && (
                        <div className="text-sm text-muted">{`Increment: ${draft.numericStep}`}</div>
                    )}
                    {draft.numericPassingEnabled && draft.numericPassingThreshold ? (
                        <LemonTag
                            type="success"
                            className="self-start"
                            icon={<IconCheck />}
                            wrap
                        >{`Pass ${draft.numericPassingOperator === 'gte' ? '≥' : '≤'} ${draft.numericPassingThreshold}`}</LemonTag>
                    ) : (
                        <span className="text-sm text-muted">No passing rule</span>
                    )}
                </div>
            ) : (
                <div className="flex flex-col gap-2" aria-label="Score preview">
                    <h4 className="mb-0">Possible results</h4>
                    {(draft.kind === 'boolean'
                        ? [
                              { label: draft.trueLabel || 'True', passing: draft.booleanPassing === 'true' },
                              { label: draft.falseLabel || 'False', passing: draft.booleanPassing === 'false' },
                          ]
                        : draft.options.map((option) => ({
                              label: option.label || 'Unnamed category',
                              passing: draft.categoricalPassingEnabled
                                  ? draft.categoricalPassingCategories.includes(getScoreDefinitionOptionKey(option))
                                  : null,
                          }))
                    ).map((option, index) => (
                        <div key={index} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                            <span className="break-words min-w-0">{option.label}</span>
                            {option.passing !== null && (
                                <LemonTag
                                    type={option.passing ? 'success' : 'danger'}
                                    icon={option.passing ? <IconCheck /> : <IconX />}
                                >
                                    {option.passing ? 'Pass' : 'Fail'}
                                </LemonTag>
                            )}
                        </div>
                    ))}
                    {draft.kind === 'categorical' && (
                        <p className="text-sm text-muted mb-0">
                            {draft.selectionMode === 'multiple'
                                ? 'Multiple categories allowed.'
                                : 'One category per result.'}
                            {!draft.categoricalPassingEnabled && ' No passing rule.'}
                        </p>
                    )}
                    {draft.kind === 'categorical' && draft.selectionMode === 'multiple' && (
                        <>
                            {draft.categoricalMinSelections && (
                                <p className="text-sm text-muted mb-0">{`Minimum selections: ${draft.categoricalMinSelections}`}</p>
                            )}
                            {draft.categoricalMaxSelections && (
                                <p className="text-sm text-muted mb-0">{`Maximum selections: ${draft.categoricalMaxSelections}`}</p>
                            )}
                        </>
                    )}
                </div>
            )}
            {draft.calculation === 'composite' && (
                <div className="border-t pt-4 flex flex-col gap-3">
                    <h4 className="mb-0">Inputs</h4>
                    {inputSummary ??
                        (draft.inputs.length ? (
                            <ul className="list-none m-0 p-0 space-y-2">
                                {draft.inputs.map((input, index) => (
                                    <li key={index} className="flex flex-wrap justify-between gap-1 text-sm">
                                        <span className="break-words">{input.name}</span>
                                        <span className="text-muted">{`v${input.version}`}</span>
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <p className="text-sm text-muted mb-0">Add scorers to build your formula.</p>
                        ))}
                    {draft.expression && (
                        <div className="flex flex-col gap-2 min-w-0">
                            <h4 className="mb-0">Formula</h4>
                            <div className="text-sm border rounded bg-bg-light p-3">
                                <CodeLine
                                    language={Language.Python}
                                    wrapLines
                                    text={formatCompositeExpression(draft.expression)}
                                />
                            </div>
                        </div>
                    )}
                </div>
            )}
        </LemonCard>
    )
}
