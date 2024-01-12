import { LemonCard, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs } from '~/types'

import { pipelineOverviewLogic } from './overviewLogic'

type PipelineStepProps = {
    order?: number
    name: string
    description?: string
    status?: string
    to: string
    success_rate?: number
}

const PipelineStep = ({ name, description, to }: PipelineStepProps): JSX.Element => (
    <LemonCard
        className="cursor-pointer"
        onClick={() => {
            router.actions.push(to)
        }}
    >
        <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-primary" />
        </span>

        <h3>{name}</h3>
        {description ? (
            <LemonMarkdown className="row-description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        ) : (
            <p className="italic">No description.</p>
        )}
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
                        <PipelineStep key={d.id} name={d.name} description={d.description} to={d.config_url} />
                    ))}
                    {/* <pre>{JSON.stringify(destinations, null, 2)}</pre> */}
                </div>
            )}
        </div>
    )
}
