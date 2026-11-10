import { IconPerson } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { LabeledLink } from '../types'
import { LabeledChipValue } from './LabeledChipValue'

export interface PersonChipProps {
    person: LabeledLink
}

export function PersonChip({ person }: PersonChipProps): JSX.Element {
    return (
        <Link to={person.href} subtle className="inline-flex min-w-0">
            <LemonTag weight="normal" className="max-w-full">
                <LabeledChipValue label="Person" icon={<IconPerson />}>
                    {person.label}
                </LabeledChipValue>
            </LemonTag>
        </Link>
    )
}
