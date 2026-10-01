import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { ReplayTabs } from '~/types'

import { FilterTemplates } from './FilterTemplates'

const SessionRecordingTemplates = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-4">
            <p className="mb-0">
                Use a template to find a focus area, then watch the filtered replays to see where users struggle and
                what could be made more clear.
            </p>
            <FilterTemplates
                source="templates_tab"
                onApply={({ order, ...filters }) =>
                    router.actions.push(urls.replay(ReplayTabs.Home, filters, undefined, order))
                }
            />
        </div>
    )
}

export default SessionRecordingTemplates
