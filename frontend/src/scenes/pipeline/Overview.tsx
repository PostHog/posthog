import { LemonCard, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import { PipelineAppKind, PipelineAppTab, PluginConfigWithPluginInfoNew, PluginType } from '~/types'

import { AppMetricSparkLine } from './AppMetricSparkLine'
import { DestinationMoreOverlay } from './Destinations'
import { DestinationType, PipelineAppBackend } from './destinationsLogic'
import { pipelineOverviewLogic } from './overviewLogic'
import { TransformationsMoreOverlay } from './Transformations'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { humanFriendlyFrequencyName } from './utils'

type PipelineStepProps = {
    order?: number
    name: string
    to: string
    description?: string
    headerInfo: JSX.Element
    additionalInfo?: JSX.Element
    plugin?: PluginType | null
}

const PipelineStep = ({
    order,
    name,
    to,
    description,
    headerInfo,
    additionalInfo,
    plugin,
}: PipelineStepProps): JSX.Element => (
    <LemonCard>
        {order !== undefined && (
            <div className="mb-3">
                <SeriesGlyph
                    style={{
                        color: 'var(--muted)',
                        borderColor: 'var(--muted)',
                    }}
                >
                    {order}
                </SeriesGlyph>
            </div>
        )}

        <div className="flex items-center justify-between mb-3 min-h-13">
            <div className="flex items-center">
                {plugin && <PluginImage plugin={plugin} size="small" />}
                <h3 className={clsx('mb-0 mr-2', { 'ml-3': plugin })}>
                    <Link to={to} subtle>
                        {name}
                    </Link>
                </h3>
            </div>

            <div className="flex items-center">{headerInfo}</div>
        </div>
        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <span className="italic">No description.</span>
        )}
        {additionalInfo && <div className="mt-3 flex flex-end">{additionalInfo}</div>}
    </LemonCard>
)

const PipelineStepSkeleton = (): JSX.Element => (
    <LemonCard>
        <LemonSkeleton className="h-5 w-1/3 mb-3" />
        <LemonSkeleton className="h-4 w-3/4 mb-3" />
        <LemonSkeleton className="h-4 w-1/2" />
    </LemonCard>
)

const PipelineStepTransformation = ({
    transformation,
}: {
    transformation: PluginConfigWithPluginInfoNew
}): JSX.Element => {
    const { sortedEnabledPluginConfigs } = useValues(pipelineTransformationsLogic)

    return (
        <PipelineStep
            order={sortedEnabledPluginConfigs.findIndex((pc) => pc.id === transformation.id) + 1}
            name={transformation.name}
            to={urls.pipelineApp(PipelineAppKind.Transformation, transformation.id, PipelineAppTab.Configuration)}
            description={transformation.description}
            headerInfo={
                <>
                    <div className="mr-1">
                        <AppMetricSparkLine config={transformation} />
                    </div>
                    <More overlay={<TransformationsMoreOverlay pluginConfig={transformation} inOverview />} />
                </>
            }
            plugin={transformation.plugin_info}
        />
    )
}

const PipelineStepDestination = ({ destination }: { destination: DestinationType }): JSX.Element => {
    return (
        <PipelineStep
            name={destination.name}
            to={destination.config_url}
            description={destination.description}
            headerInfo={
                <>
                    <div className="mr-1">
                        <AppMetricSparkLine config={destination} />
                    </div>
                    <More overlay={<DestinationMoreOverlay destination={destination} inOverview />} />
                </>
            }
            additionalInfo={
                <div className="flex gap-1">
                    <LemonTag type="primary">{humanFriendlyFrequencyName(destination.frequency)}</LemonTag>
                    {destination.backend === PipelineAppBackend.BatchExport}
                </div>
            }
            plugin={destination.backend === PipelineAppBackend.Plugin ? destination.plugin : undefined}
        />
    )
}

export function Overview(): JSX.Element {
    const { transformations, destinations, transformationsLoading, destinationsLoading } =
        useValues(pipelineOverviewLogic)

    return (
        <div>
            <h2>Filters</h2>
            <p>
                <i>Coming soon.</i>
            </p>

            <h2 className="mt-4">Transformations</h2>
            <div className="grid grid-cols-3 gap-4">
                {transformationsLoading ? (
                    <PipelineStepSkeleton />
                ) : (
                    transformations &&
                    transformations
                        .filter((t) => t.enabled)
                        .map((t) => <PipelineStepTransformation key={t.id} transformation={t} />)
                )}
            </div>

            <h2 className="mt-4">Destinations</h2>
            <div className="grid grid-cols-3 gap-4">
                {destinationsLoading ? (
                    <PipelineStepSkeleton />
                ) : (
                    destinations &&
                    destinations
                        .filter((d) => d.enabled)
                        .map((d) => <PipelineStepDestination key={d.id} destination={d} />)
                )}
            </div>
        </div>
    )
}
