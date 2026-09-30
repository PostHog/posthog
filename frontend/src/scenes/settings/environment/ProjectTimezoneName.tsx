import { useValues } from 'kea'

import { teamLogic } from '~/scenes/teamLogic'

/** Renders the project's timezone name inline, for setting descriptions that mention it. */
export function ProjectTimezoneName(): JSX.Element {
    const { timezone } = useValues(teamLogic)
    return <span translate="no">{timezone}</span>
}
