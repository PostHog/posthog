import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'

import { RecordingUniversalFilters, ReplayTemplateCategory, ReplayTemplateType } from '~/types'

import { ReplayTemplateUsedSource, sessionReplayTemplatesLogic } from './sessionRecordingTemplatesLogic'
import { SingleTemplateVariable } from './SingleTemplateVariable'

export function FilterTemplateCard({
    template,
    category,
    source,
    onApply,
}: {
    template: ReplayTemplateType
    category: ReplayTemplateCategory
    source: ReplayTemplateUsedSource
    onApply: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const logicProps = { template, category }
    const {
        editableVariables,
        filtersToApply,
        previewFilters,
        hasTemplateFilters,
        canApplyFilters,
        variablesVisible,
        matchCount,
        matchCountLoading,
        matchCountError,
    } = useValues(sessionReplayTemplatesLogic(logicProps))
    const { showVariables, hideVariables, reportTemplateUsed } = useActions(sessionReplayTemplatesLogic(logicProps))

    const applyTemplate = (): void => {
        reportTemplateUsed(source)
        onApply(filtersToApply)
    }

    return (
        <LemonCard
            className="w-full"
            onClick={() => showVariables()}
            focused={variablesVisible}
            closeable={variablesVisible}
            onClose={hideVariables}
            data-attr="session-replay-template"
            data-ph-capture-attribute-category={category}
            data-ph-capture-attribute-template={template.key}
        >
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    {template.icon ? (
                        <div className="bg-surface-primary rounded p-2 w-8 h-8 flex items-center justify-center">
                            {template.icon}
                        </div>
                    ) : null}
                    <h3 className="mb-0">
                        <Link
                            data-attr="templates-show-variables"
                            onClick={() => showVariables()}
                            className="text-accent"
                        >
                            {template.name}
                        </Link>
                    </h3>
                </div>
                <p className="mb-0">{template.description}</p>
                {variablesVisible ? (
                    <div className="flex flex-col gap-3 pt-2 border-t">
                        {editableVariables.map((variable) => (
                            <SingleTemplateVariable key={variable.key} variable={variable} {...logicProps} />
                        ))}
                        <div className="flex flex-col gap-1">
                            <span className="text-xs font-semibold">Filters this will apply</span>
                            <div className="flex flex-wrap items-center gap-1">
                                {previewFilters.map((filter, index) => (
                                    <UniversalFilterButton key={index} filter={filter} />
                                ))}
                                {template.order ? (
                                    <LemonTag type="muted">Sorted by {template.order.replaceAll('_', ' ')}</LemonTag>
                                ) : null}
                                {previewFilters.length === 0 && !template.order ? (
                                    <span className="text-xs text-secondary">Set a value above to see the filters</span>
                                ) : null}
                            </div>
                        </div>
                        <span className="text-xs text-secondary flex items-center gap-1">
                            {matchCountLoading ? (
                                <>
                                    <Spinner className="text-sm" /> Counting recordings in the last 7 days
                                </>
                            ) : matchCountError ? (
                                'Could not count recordings. You can still apply the filters.'
                            ) : matchCount && hasTemplateFilters ? (
                                matchCount.count === 0 ? (
                                    'No recordings in the last 7 days. Change the filters.'
                                ) : (
                                    `${matchCount.count}${matchCount.hasMore ? '+' : ''} ${matchCount.count === 1 && !matchCount.hasMore ? 'recording' : 'recordings'} in the last 7 days`
                                )
                            ) : null}
                        </span>
                        <div>
                            <LemonButton
                                type="primary"
                                onClick={applyTemplate}
                                disabledReason={
                                    !canApplyFilters ? 'Please set a value for at least one variable' : undefined
                                }
                                data-attr="session-replay-filter-template-apply"
                            >
                                Apply filters
                            </LemonButton>
                        </div>
                    </div>
                ) : null}
            </div>
        </LemonCard>
    )
}
