import { useActions, useValues } from 'kea'

import { IconCalendar, IconQuestion, IconUser, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ScoutCreateButton } from 'products/signals/frontend/inbox/components/config/scouts/ScoutCreateButton'
import { ScoutRowCard } from 'products/signals/frontend/inbox/components/config/scouts/ScoutRowCard'
import { scoutFleetLogic } from 'products/signals/frontend/inbox/logics/scoutFleetLogic'

import {
    AI_OBSERVABILITY_SCOUT_TEMPLATES,
    AIObservabilityScoutTemplate,
    isAIObservabilityScout,
} from './aiObservabilityScoutTemplates'

const SCOUTS_DOCS_URL = 'https://posthog.com/docs/ai-observability/self-driving'

const TEMPLATE_ICONS: Record<AIObservabilityScoutTemplate['key'], JSX.Element> = {
    'daily-digest': <IconCalendar />,
    'costly-users': <IconUser />,
    'error-patterns': <IconWarning />,
}

function ScoutTemplateCard({ template }: { template: AIObservabilityScoutTemplate }): JSX.Element {
    const { loadScoutConfigs } = useActions(scoutFleetLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-3">
            <div className="flex min-w-0 items-start gap-2">
                <span className="mt-0.5 shrink-0 text-muted">{TEMPLATE_ICONS[template.key]}</span>
                <div className="min-w-0">
                    <h3 className="m-0 text-sm font-semibold">{template.title}</h3>
                    <p className="m-0 text-xs text-muted">{template.description}</p>
                </div>
            </div>
            <div className="mt-auto flex items-center justify-between gap-2">
                <LemonTag type="muted" size="small">
                    {template.schedule}
                </LemonTag>
                <ScoutCreateButton
                    initialValues={template.initialValues}
                    onCreated={() => loadScoutConfigs()}
                    data-attr={`create-${template.key}-scout`}
                >
                    Use template
                </ScoutCreateButton>
            </div>
        </LemonCard>
    )
}

export function AIObservabilitySelfDriving(): JSX.Element {
    const { scoutConfigs, scoutConfigsLoading, deletingScoutIds, updatingScoutIds } = useValues(scoutFleetLogic)
    const { deleteScout, loadScoutConfigs, updateScoutConfig } = useActions(scoutFleetLogic)

    const aiObservabilityScouts = scoutConfigs?.filter(isAIObservabilityScout) ?? []

    let scoutsContent: JSX.Element
    if (scoutConfigsLoading && scoutConfigs === null) {
        scoutsContent = (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-16 w-full rounded" />
                <LemonSkeleton className="h-16 w-full rounded" />
            </div>
        )
    } else if (scoutConfigs === null) {
        scoutsContent = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: () => loadScoutConfigs() }}
                data-attr="ai-observability-scouts-load-error"
            >
                We couldn't load your AI observability scouts. Try again in a moment.
            </LemonBanner>
        )
    } else if (aiObservabilityScouts.length === 0) {
        scoutsContent = (
            <LemonCard hoverEffect={false} className="p-4 text-sm text-muted">
                No AI observability scouts yet. Use a template above to create one.
            </LemonCard>
        )
    } else {
        scoutsContent = (
            <div className="flex flex-col gap-2">
                {aiObservabilityScouts.map((config) => (
                    <ScoutRowCard
                        key={config.id}
                        config={config}
                        rollup={undefined}
                        onUpdate={updateScoutConfig}
                        onDelete={deleteScout}
                        deleting={deletingScoutIds.includes(config.id)}
                        updating={updatingScoutIds.includes(config.id)}
                    />
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">Start with a template</h2>
                        <Tooltip
                            title="Each template is a pre-defined scout – a scheduled agent that explores your AI observability data and surfaces findings worth reviewing. Actionable scout reports land in your inbox."
                            docLink={SCOUTS_DOCS_URL}
                        >
                            <span
                                className="inline-flex items-center gap-1 text-xs text-muted hover:text-default cursor-pointer transition-colors"
                                data-attr="ai-observability-scout-templates-what-is-this"
                            >
                                <IconQuestion className="text-sm" />
                                What is this?
                            </span>
                        </Tooltip>
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Choose a starting point, then review and edit it before saving.
                    </p>
                </div>
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                    {AI_OBSERVABILITY_SCOUT_TEMPLATES.map((template) => (
                        <ScoutTemplateCard key={template.key} template={template} />
                    ))}
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <div>
                    <div className="flex items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">Your AI observability scouts</h2>
                        {scoutConfigs !== null ? (
                            <LemonTag type="muted" size="small">
                                {aiObservabilityScouts.length}
                            </LemonTag>
                        ) : null}
                    </div>
                    <p className="m-0 text-sm text-muted">
                        Add the <code>ai-observability</code> label to a scout for it to appear here.
                    </p>
                </div>
                {scoutsContent}
            </section>
        </div>
    )
}
