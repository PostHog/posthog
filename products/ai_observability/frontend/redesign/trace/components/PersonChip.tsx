import { IconPerson } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'

export interface PersonChipProps {
    person: LabeledLink
}

export function PersonChip({ person }: PersonChipProps): JSX.Element {
    return (
        <Link to={person.href} subtle className="inline-flex min-w-0">
            <LemonTag icon={<IconPerson />} weight="normal" className="max-w-full">
                <span className="max-w-60 truncate">{person.label}</span>
            </LemonTag>
        </Link>
    )
}
