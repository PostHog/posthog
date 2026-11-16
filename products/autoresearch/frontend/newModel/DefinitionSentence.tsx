import { useActions, useValues } from 'kea'

import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { HORIZON_PRESETS, autoresearchNewLogic } from '../autoresearchNewLogic'
import { PopulationPicker } from './PopulationPicker'

function formatDays(days: number): string {
    return Number.isFinite(days) ? `${days} ${days === 1 ? 'day' : 'days'}` : 'N days'
}

export function DefinitionSentence(): JSX.Element {
    const { newPipeline, newPipelineErrors, resolvedTemplate } = useValues(autoresearchNewLogic)
    const { setNewPipelineValues } = useActions(autoresearchNewLogic)
    const hasTemplate = newPipeline.template_key !== null
    const definitionError =
        newPipelineErrors.population_choice ??
        newPipelineErrors.target_event ??
        newPipelineErrors.target_action_id ??
        newPipelineErrors.horizon_days

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2 text-base">
                <span>Predict who among</span>
                <PopulationPicker />
                <span>will</span>
                <TaxonomicPopover
                    type="secondary"
                    size="small"
                    groupType={TaxonomicFilterGroupType.Events}
                    groupTypes={
                        hasTemplate
                            ? [TaxonomicFilterGroupType.Events]
                            : [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
                    }
                    value={
                        newPipeline.target_type === 'action' ? newPipeline.target_action_id : newPipeline.target_event
                    }
                    onChange={(picked, groupType, item) => {
                        if (groupType === TaxonomicFilterGroupType.Actions) {
                            setNewPipelineValues({
                                target_type: 'action',
                                target_action_id: typeof picked === 'number' ? picked : Number(picked),
                                target_event: item?.name ?? `action ${picked}`,
                            })
                        } else {
                            setNewPipelineValues({
                                target_type: 'event',
                                target_event: String(picked ?? ''),
                                target_action_id: null,
                            })
                        }
                    }}
                    renderValue={() => <>{newPipeline.target_event || 'do something'}</>}
                    placeholder="do something"
                    allowClear
                    data-attr="autoresearch-new-target"
                />
                <span>within the next</span>
                <LemonDropdown
                    closeOnClickInside={false}
                    placement="bottom-start"
                    overlay={
                        <div className="flex flex-col gap-2 p-2">
                            <div className="flex gap-1">
                                {HORIZON_PRESETS.map((days) => (
                                    <LemonButton
                                        key={days}
                                        type="secondary"
                                        size="small"
                                        active={newPipeline.horizon_days === days}
                                        onClick={() => setNewPipelineValues({ horizon_days: days })}
                                        data-attr={`autoresearch-new-horizon-${days}`}
                                    >
                                        {formatDays(days)}
                                    </LemonButton>
                                ))}
                            </div>
                            <LemonField name="horizon_days" label="Days">
                                <LemonInput type="number" min={1} max={365} size="small" />
                            </LemonField>
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="small" data-attr="autoresearch-new-horizon">
                        {formatDays(newPipeline.horizon_days)}
                    </LemonButton>
                </LemonDropdown>
            </div>
            {definitionError && <div className="text-danger text-xs">{definitionError}</div>}
            {hasTemplate && !newPipeline.target_event && (
                <div className="text-muted text-xs">Pick the event this template predicts.</div>
            )}
            {resolvedTemplate?.resolved_activity_event && (
                <div className="text-muted text-xs">
                    The template picked {resolvedTemplate.resolved_activity_event} as the activity event from your data.
                    Change the target to use another event.
                </div>
            )}
        </div>
    )
}
