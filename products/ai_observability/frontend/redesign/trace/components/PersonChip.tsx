import { IconPerson } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { PersonLink } from '../types'

export interface PersonChipProps {
    person: PersonLink
}

export function PersonChip({ person }: PersonChipProps): JSX.Element {
    return (
        <Link to={person.href} subtle>
            <LemonTag icon={<IconPerson />} weight="normal">
                {person.label}
            </LemonTag>
        </Link>
    )
}
