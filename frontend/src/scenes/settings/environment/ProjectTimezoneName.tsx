import { useValues } from 'kea'

import { teamLogic } from '~/scenes/teamLogic'

export function ProjectTimezoneName(): JSX.Element {
    const { timezone } = useValues(teamLogic)
    return <span translate="no">{timezone}</span>
}
