import { useValues } from 'kea'

import { IconPlusSmall, IconSparkles } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, InsightType } from '~/types'

import { AiSketch, GenericInsightSketch, INSIGHT_TYPE_SKETCHES } from './InsightTypeSketch'

interface NewInsightCardProps {
    name: string
    description: string
    icon: React.ComponentType<{ className?: string }>
    iconClassName?: string
    sketch: JSX.Element
    to: string
    dataAttr: string
    onClick?: () => void
}

function NewInsightCard({
    name,
    description,
    icon: Icon,
    iconClassName = 'text-secondary',
    sketch,
    to,
    dataAttr,
    onClick,
}: NewInsightCardProps): JSX.Element {
    return (
        <Link
            to={to}
            data-attr={dataAttr}
            onClick={onClick}
            className={cn(
                'flex flex-col overflow-hidden rounded border border-primary bg-surface-primary',
                'transition-all duration-100 hover:-translate-y-0.5 hover:border-accent hover:shadow-md',
                'focus-visible:border-accent'
            )}
        >
            <div className="shrink-0 border-b border-primary bg-fill-secondary">{sketch}</div>
            <div className="flex flex-1 flex-col gap-0.5 p-2">
                <div className="flex items-center gap-1.5">
                    <Icon className={cn('text-base shrink-0', iconClassName)} />
                    <span className="text-sm font-semibold text-default">{name}</span>
                </div>
                <span className="text-xs leading-snug text-secondary">{description}</span>
            </div>
        </Link>
    )
}

export function NewInsightMenuOverlay(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const insightEntries = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([insightType, metadata]) =>
            metadata.inMenu &&
            insightType !== InsightType.JSON &&
            (featureFlags[FEATURE_FLAGS.HOG] || insightType !== InsightType.HOG)
    )

    return (
        <div className="w-[42rem] max-w-[calc(100vw-1rem)] p-1" data-attr="new-insight-type-picker">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                <NewInsightCard
                    name="AI"
                    description="Ask PostHog AI to create insights using natural language."
                    icon={IconSparkles}
                    iconClassName="text-ai"
                    sketch={<AiSketch />}
                    to={urls.ai()}
                    dataAttr="new-insight-menu-ai"
                />
                {insightEntries.map(([insightType, metadata]) => {
                    const Sketch = INSIGHT_TYPE_SKETCHES[insightType as InsightType] ?? GenericInsightSketch
                    return (
                        <NewInsightCard
                            key={insightType}
                            name={metadata.name}
                            description={metadata.description ?? ''}
                            icon={metadata.icon}
                            sketch={<Sketch />}
                            to={INSIGHT_TYPE_URLS[insightType as InsightType]}
                            dataAttr={`new-insight-menu-${insightType.toLowerCase()}`}
                            onClick={() => eventUsageLogic.actions.reportSavedInsightNewInsightClicked(insightType)}
                        />
                    )
                })}
            </div>
        </div>
    )
}

export function NewInsightButton(): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Insight}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Shortcut
                name="NewInsight"
                keybind={[keyBinds.new]}
                intent="New insight"
                interaction="click"
                scope={Scene.SavedInsights}
                priority={100}
            >
                <LemonDropdown overlay={<NewInsightMenuOverlay />} placement="bottom-end">
                    <LemonButton
                        type="primary"
                        data-attr="saved-insights-new-insight-button"
                        size="small"
                        icon={<IconPlusSmall />}
                        tooltip="New insight"
                    >
                        New
                    </LemonButton>
                </LemonDropdown>
            </Shortcut>
        </AccessControlAction>
    )
}
