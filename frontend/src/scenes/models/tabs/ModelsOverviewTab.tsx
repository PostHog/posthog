import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonCard, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { modelsSceneLogic } from '../modelsSceneLogic'

const NAMES_SHOWN = 3

function namesSummary(names: string[]): string {
    const shown = names.slice(0, NAMES_SHOWN).join(', ')
    const rest = names.length - NAMES_SHOWN
    return rest > 0 ? `${shown} and ${rest} more` : shown
}

interface AttentionTileProps {
    title: string
    count: number
    detail: string
    tone: 'danger' | 'warning'
    'data-attr': string
}

function AttentionTile({ title, count, detail, tone, ...props }: AttentionTileProps): JSX.Element {
    return (
        <LemonCard className="flex flex-col gap-1" data-attr={props['data-attr']}>
            <span className="text-xs uppercase text-secondary">{title}</span>
            <span className={`text-2xl font-semibold ${tone === 'danger' ? 'text-danger' : 'text-warning'}`}>
                {count}
            </span>
            <span className="text-xs text-secondary truncate">{detail}</span>
        </LemonCard>
    )
}

export function ModelsOverviewTab(): JSX.Element {
    const { failingNodes, suspendedViews } = useValues(modelsSceneLogic)

    const nothingToDo = failingNodes.length === 0 && suspendedViews.length === 0

    return (
        <div className="flex flex-col gap-4">
            {nothingToDo ? (
                <LemonCard hoverEffect={false} className="flex items-center gap-2" data-attr="models-overview-healthy">
                    <IconCheckCircle className="text-lg text-success" />
                    <span className="text-sm">Every model ran as scheduled. Nothing needs your attention.</span>
                </LemonCard>
            ) : (
                <div className="@container">
                    <div className="grid grid-cols-1 @md:grid-cols-2 @4xl:grid-cols-3 gap-2">
                        {failingNodes.length > 0 && (
                            <AttentionTile
                                title="Failing"
                                count={failingNodes.length}
                                detail={namesSummary(failingNodes.map((node) => node.name))}
                                tone="danger"
                                data-attr="models-overview-failing"
                            />
                        )}
                        {suspendedViews.length > 0 && (
                            <AttentionTile
                                title="Suspended"
                                count={suspendedViews.length}
                                detail={namesSummary(suspendedViews.map((view) => view.name))}
                                tone="warning"
                                data-attr="models-overview-suspended"
                            />
                        )}
                    </div>
                </div>
            )}
            <p className="text-xs text-secondary">
                Open a model from the <Link to={urls.models('models')}>Models</Link> tab to see its runs, errors, and
                schedule.
            </p>
        </div>
    )
}
