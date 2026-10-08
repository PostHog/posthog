import { IconPerson } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'

export interface PersonChipProps {
    person: LabeledLink
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
