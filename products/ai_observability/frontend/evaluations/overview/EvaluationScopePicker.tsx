import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Picks which evaluations the overview shows. A button like the date range, so the header controls line up. */
export function EvaluationScopePicker(): JSX.Element {
    const { scopeEvaluations, pickedIds } = useValues(evaluationsOverviewLogic)
    const { setPickedIds } = useActions(evaluationsOverviewLogic)
    const [search, setSearch] = useState('')
    const matching = scopeEvaluations.filter((evaluation) =>
        evaluation.name.toLowerCase().includes(search.toLowerCase())
    )
    const toggle = (id: string): void =>
        setPickedIds(pickedIds.includes(id) ? pickedIds.filter((current) => current !== id) : [...pickedIds, id])

    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={
                <div className="flex flex-col gap-1 w-72 max-h-96">
                    <LemonInput
                        type="search"
                        size="small"
                        autoFocus
                        prefix={<IconSearch />}
                        placeholder="Search evaluations"
                        value={search}
                        onChange={setSearch}
                    />
                    <div className="flex flex-col overflow-y-auto">
                        {matching.length === 0 ? (
                            <div className="px-2 py-1 text-secondary">No evaluations match this search</div>
                        ) : (
                            matching.map((evaluation) => (
                                <LemonCheckbox
                                    key={evaluation.id}
                                    fullWidth
                                    size="small"
                                    className="px-2 py-1"
                                    checked={pickedIds.includes(evaluation.id)}
                                    onChange={() => toggle(evaluation.id)}
                                    label={evaluation.name}
                                />
                            ))
                        )}
                    </div>
                    {pickedIds.length > 0 && (
                        <LemonButton
                            size="small"
                            fullWidth
                            center
                            onClick={() => setPickedIds([])}
                            data-attr="evaluation-overview-scope-clear"
                        >
                            Show all evaluations
                        </LemonButton>
                    )}
                </div>
            }
        >
            <LemonButton type="secondary" size="small" data-attr="evaluation-overview-scope-picker">
                {pickedIds.length === 0 ? 'All evaluations' : pluralize(pickedIds.length, 'evaluation')}
            </LemonButton>
        </LemonDropdown>
    )
}
