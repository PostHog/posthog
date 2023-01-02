import { PropertyFilterType } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { IconCohort, IconPerson, UnverifiedEvent } from 'lib/components/icons'

export function PropertyFilterIcon({ type }: { type?: PropertyFilterType }): JSX.Element {
    let iconElement = <></>
    switch (type) {
        case 'event':
            iconElement = (
                <Tooltip title={'Event property'}>
                    <UnverifiedEvent width={14} height={14} />
                </Tooltip>
            )
            break
        case 'person':
            iconElement = (
                <Tooltip title={'Person property'}>
                    <IconPerson />
                </Tooltip>
            )
            break
        case 'cohort':
            iconElement = (
                <Tooltip title={'Cohort filter'}>
                    <IconCohort />
                </Tooltip>
            )
            break
    }
    return iconElement
}
