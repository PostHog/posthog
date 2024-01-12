import { LemonCard, LemonSegmentedButton, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { pipelineOverviewLogic } from './overviewLogic'

type PipelineStepProps = {
    order?: number
    name: string
    description?: string
    enabled?: boolean
    to: string
    success_rate?: number
}

const PipelineStep = ({ name, description, order, enabled, to }: PipelineStepProps): JSX.Element => (
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
                    <Link to={to}>{name}</Link>
                </h3>
                <Tooltip title="xx events processed in the last 7 days" placement="right">
                    <span className="relative flex h-3 w-3">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                        <span className="relative inline-flex rounded-full h-3 w-3 bg-primary" />
                    </span>
                </Tooltip>
            </div>
            <div>
                <More overlay={<></>} />
            </div>
        </div>

        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <p className="italic">No description.</p>
        )}

        <div>
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
                        />
                    ))}
                    {/* <pre>{JSON.stringify(transformations, null, 2)}</pre> */}
                </div>
            )}

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
                        />
                    ))}
                    {/* <pre>{JSON.stringify(destinations, null, 2)}</pre> */}
                </div>
            )}
        </div>
    )
}
