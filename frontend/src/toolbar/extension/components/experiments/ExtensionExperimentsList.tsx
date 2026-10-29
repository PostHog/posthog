import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'

import { urls } from '~/toolbar/shared/urls'

import { extensionExperimentsLogic } from '../../logics/panel/extensionExperimentsLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionEntityList } from '../panel/ExtensionEntityList'

export function ExtensionExperimentsList(): JSX.Element {
    const { experimentsState, filteredExperiments, searchTerm } = useValues(extensionExperimentsLogic)
    const { setSearchTerm, selectExperiment } = useActions(extensionExperimentsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)
    const saveResult = experimentsState?.saveResult

    return (
        <ExtensionEntityList
            noun="experiment"
            pluralNoun="experiments"
            items={experimentsState ? filteredExperiments : null}
            loading={!!experimentsState?.loading}
            searchTerm={searchTerm}
            onSearch={setSearchTerm}
            onSelect={selectExperiment}
            onCreate={() => selectExperiment('new')}
            saved={
                saveResult?.status === 'saved'
                    ? { name: saveResult.name, url: projectUrl(urls.experiment(saveResult.experimentId)) }
                    : null
            }
            viewAllUrl={projectUrl(urls.experiments())}
            emptyText="This project has no web experiments yet."
            notice={
                experimentsState?.webExperimentsDisabled && (
                    <LemonBanner type="warning">
                        Web experiments are off in this page's PostHog setup. To run experiments, set{' '}
                        <code>disable_web_experiments: false</code> in your configuration.{' '}
                        <Link
                            target="_blank"
                            targetBlankIcon
                            to="https://posthog.com/docs/experiments/no-code-web-experiments"
                        >
                            Learn more
                        </Link>
                    </LemonBanner>
                )
            }
            dataAttrs={{
                search: 'toolbar-extension-experiments-search',
                row: 'toolbar-extension-experiment-row',
                create: 'toolbar-extension-new-experiment',
                openSaved: 'toolbar-extension-open-saved-experiment',
            }}
        />
    )
}
