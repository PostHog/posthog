import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { Experiment } from '~/types'

interface WebExperimentImplementationDetails {
    experiment: Partial<Experiment> | null
}
export function WebExperimentImplementationDetails({ experiment }: WebExperimentImplementationDetails): JSX.Element {
    return (
        <>
            <div>
                <h2 className="font-semibold text-lg mb-2">Implementation</h2>
                <div className="border px-6 rounded bg-bg-light">
                    <div className="font-semibold leading-tight text-base text-current mb-4 my-4">
                        This web experiment's implementation can be edited in the toolbar.
                    </div>
                    <div className="m-4">
                        <AuthorizedUrlList
                            experimentId={experiment?.id}
                            type={AuthorizedUrlListType.TOOLBAR_URLS}
                            addText="Add authorized URL"
                        />
                    </div>
                </div>
            </div>
        </>
    )
}
