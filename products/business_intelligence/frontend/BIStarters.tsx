import { useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { BICatalogMetricPicker } from './BICatalogMetricPicker'
import { captureBIWorksheetAction } from './biEditorAnalytics'
import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { BI_QUESTION_STARTERS, starterWorksheetUrl } from './biQuestionStarters'
import { biStartersLogic } from './biStartersLogic'

export function BIStarters(): JSX.Element {
    const { sources } = useValues(biStartersLogic)
    return (
        <section className="flex flex-col gap-2" aria-label="Worksheet starting points">
            <h3 className="m-0">Start with a question</h3>
            <div className="flex flex-wrap gap-2">
                <BICatalogMetricPicker />
                {sources.map((source) => {
                    const config = { ...DEFAULT_BI_CONFIG, source: { table: source.target_name } }
                    return (
                        <LemonButton
                            key={source.id}
                            type="secondary"
                            size="small"
                            className="max-w-full"
                            to={starterWorksheetUrl(config)}
                            tooltip={source.notes}
                            onClick={() =>
                                captureBIWorksheetAction('starter_selected', config, {
                                    starter_kind: 'certified_source',
                                })
                            }
                        >
                            <span className="flex items-center gap-1 min-w-0">
                                <span className="truncate">Explore {source.target_name}</span>
                                <LemonTag type="success">Certified</LemonTag>
                            </span>
                        </LemonButton>
                    )
                })}
                {BI_QUESTION_STARTERS.map((starter) => (
                    <LemonButton
                        key={starter.id}
                        type="secondary"
                        size="small"
                        className="max-w-full"
                        to={starterWorksheetUrl(starter.config)}
                        onClick={() =>
                            captureBIWorksheetAction('starter_selected', starter.config, { starter_kind: starter.id })
                        }
                    >
                        <span className="flex min-w-0 flex-col items-start whitespace-normal py-1 text-left">
                            <span>{starter.title}</span>
                            <span className="text-xs font-normal text-secondary">{starter.description}</span>
                        </span>
                    </LemonButton>
                ))}
            </div>
            <p className="m-0 text-xs text-secondary">
                Choose a starting point, add fields, then Run. Save your worksheet to return to it or add it to a
                dashboard.
            </p>
        </section>
    )
}
