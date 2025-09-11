import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { ExperimentsEditingToolbarMenu } from '~/toolbar/experiments/ExperimentsEditingToolbarMenu'
import { ExperimentsListView } from '~/toolbar/experiments/ExperimentsListView'
import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

const ExperimentsListToolbarMenu = (): JSX.Element => {
    const { searchTerm } = useValues(experimentsLogic)
    const { newExperiment } = useActions(experimentsTabLogic)
    const { setSearchTerm } = useActions(experimentsLogic)
    const { allExperiments, sortedExperiments, allExperimentsLoading } = useValues(experimentsLogic)
    const { apiURL } = useValues(toolbarConfigLogic)

    const isWebExperimentsDisabled = Boolean(window?.parent?.posthog?.config?.disable_web_experiments)

    return (
        <ToolbarMenu>
            {allExperiments.length > 10 && (
                <ToolbarMenu.Header className="px-3 mt-2">
                    <LemonInput
                        autoFocus={true}
                        fullWidth={true}
                        placeholder="Search"
                        type="search"
                        value={searchTerm}
                        onChange={(s) => setSearchTerm(s)}
                    />
                </ToolbarMenu.Header>
            )}
            <ToolbarMenu.Body>
                <div className="px-1 deprecated-space-y-px py-2">
                    {isWebExperimentsDisabled && (
                        <div className="pb-2">
                            <LemonBanner type="warning">
                                Web experiments are disabled in your PostHog web snippet configuration. To run
                                experiments, add <code>disable_web_experiments: false</code> to your configuration.{' '}
                                <Link
                                    target="_blank"
                                    targetBlankIcon
                                    to="https://posthog.com/docs/experiments/no-code-web-experiments"
                                >
                                    Learn more
                                </Link>
                            </LemonBanner>
                        </div>
                    )}
                    {allExperiments.length === 0 && allExperimentsLoading ? (
                        <div className="text-center my-4">
                            <Spinner />
                        </div>
                    ) : (
                        <ExperimentsListView experiments={sortedExperiments} />
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <div className="flex items-center justify-between flex-1">
                    <Link to={`${apiURL}${urls.experiments()}`} target="_blank">
                        View &amp; edit all experiments <IconOpenInNew />
                    </Link>
                    <LemonButton type="primary" size="small" onClick={() => newExperiment()} icon={<IconPlus />}>
                        New experiment
                    </LemonButton>
                </div>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}

export const ExperimentsToolbarMenu = (): JSX.Element => {
    const { selectedExperiment } = useValues(experimentsTabLogic)
    return selectedExperiment ? <ExperimentsEditingToolbarMenu /> : <ExperimentsListToolbarMenu />
}
