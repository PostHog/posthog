import { LemonCard, LemonSegmentedButton, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { DestinationMoreOverlay } from './Destinations'
import { pipelineOverviewLogic } from './overviewLogic'
import { TransformationsMoreOverlay } from './Transformations'

type StatusIndicatorProps = {
    status: 'enabled' | 'disabled'
}

const StatusIndicator = ({ status }: StatusIndicatorProps): JSX.Element => (
    <Tooltip title="xx events processed in the last 7 days" placement="right">
        <div className="relative flex h-3 w-3">
            <span
                className={clsx('absolute inline-flex h-full w-full rounded-full opacity-75', {
                    'bg-success animate-ping': status === 'enabled',
                    'bg-border': status === 'disabled',
                })}
            />
            <span
                className={clsx('relative inline-flex rounded-full h-3 w-3', {
                    'bg-success': status === 'enabled',
                })}
            />
        </div>
    </Tooltip>
)

type PipelineStepProps = {
    order?: number
    name: string
    description?: string
    enabled?: boolean
    to: string
    success_rate?: number
    moreOverlay?: JSX.Element
}

const PipelineStep = ({ name, description, order, enabled, to, moreOverlay }: PipelineStepProps): JSX.Element => (
    <LemonCard>
        {order && (
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

        <div className="flex items-center justify-between mb-3">
            <div className="flex items-center">
                <h3 className="mb-0 mr-2">
                    <Link to={to} subtle>
                        {name}
                    </Link>
                </h3>
                <StatusIndicator status={enabled ? 'enabled' : 'disabled'} />
            </div>
            <div>{moreOverlay && <More overlay={moreOverlay} />}</div>
        </div>

        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <span className="italic">No description.</span>
        )}

        <div className="mt-3 flex flex-end">
            {enabled !== undefined && (
                <>
                    {enabled ? (
                        <LemonTag type="success" className="uppercase">
                            Enabled
                        </LemonTag>
                    ) : (
                        <LemonTag type="default" className="uppercase">
                            Disabled
                        </LemonTag>
                    )}
                </>
            )}
        </div>
    </LemonCard>
)

export function Overview(): JSX.Element {
    const { transformations, destinations, loading } = useValues(pipelineOverviewLogic)

    return (
        <div>
            {loading && <Spinner />}
            <div className="absolute right-0">
                <LemonSegmentedButton
                    size="small"
                    value="24h"
                    options={[
                        { value: '24h', label: '24h' },
                        { value: '7d', label: '7d' },
                    ]}
                />
            </div>

            <h2>Filters</h2>
            <p>
                <i>Coming soon.</i>
            </p>

            <h2 className="mt-4">Transformations</h2>
            {transformations && (
                <div className="grid grid-cols-3 gap-4">
                    {transformations.map((t) => (
                        <PipelineStep
                            key={t.id}
                            name={t.name}
                            description={t.description}
                            order={1} // TODO
                            // enabled={} // TODO
                            to={urls.pipelineApp(PipelineTabs.Transformations, t.id, PipelineAppTabs.Configuration)}
                            moreOverlay={<TransformationsMoreOverlay pluginConfig={{}} />}
                        />
                    ))}
                </div>
            )}
            {transformations && <pre>{JSON.stringify(transformations, null, 2)}</pre>}

            <h2 className="mt-4">Destinations</h2>
            {destinations && (
                <div className="grid grid-cols-3 gap-4">
                    {destinations.map((d) => (
                        <PipelineStep
                            key={d.id}
                            name={d.name}
                            description={d.description}
                            enabled={d.enabled}
                            to={d.config_url}
                            moreOverlay={<DestinationMoreOverlay destination={d} />}
                        />
                    ))}
                </div>
            )}
            {destinations && <pre>{JSON.stringify(destinations, null, 2)}</pre>}
        </div>
    )
}
