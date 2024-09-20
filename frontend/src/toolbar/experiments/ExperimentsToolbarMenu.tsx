import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect } from 'react'
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
    const { setSearchTerm, getExperiments } = useActions(experimentsLogic)
    const { allExperiments, sortedExperiments, allExperimentsLoading } = useValues(experimentsLogic)
    const { apiURL } = useValues(toolbarConfigLogic)

    useEffect(() => {
        getExperiments()
    }, [])

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput
                    autoFocus
                    fullWidth
                    placeholder="Search"
                    type="search"
                    value={searchTerm}
                    onChange={(s) => setSearchTerm(s)}
                    className="Toolbar__top_input"
                />
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="px-1 space-y-px py-2">
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
