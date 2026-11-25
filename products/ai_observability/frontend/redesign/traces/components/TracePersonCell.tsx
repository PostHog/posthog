import { PersonDisplay, type PersonDisplayProps } from 'products/persons/frontend/components/PersonDisplay'

import type { TracePersonApi } from '../../../generated/api.schemas'
import type { TraceCellStatus } from '../../shared/cellLoads'
import { TraceCellValue } from './TraceCellValue'

export interface TracePersonCellProps {
    person: TracePersonApi | null
    status: TraceCellStatus
}

function toPersonDisplayProps(person: TracePersonApi): Pick<PersonDisplayProps, 'person' | 'displayName'> {
    return {
        // PersonDisplay renders its link only for a person that carries properties. The label is already resolved,
        // and the hover card loads the full person when it opens, so the properties stay empty.
        person: { distinct_id: person.distinctId, properties: {} },
        displayName: person.label,
    }
}

export function TracePersonCell({ person, status }: TracePersonCellProps): JSX.Element {
    return (
        <TraceCellValue status={status} skeletonWidth="w-24">
            {person === null ? null : (
                <span className="block max-w-40 min-w-0">
                    {/* Fits the chip to its label, so a click beside a short name still opens the drawer. The label
                        names a customer's end user, so autocapture must not record this element or its title. */}
                    <span
                        title={person.label}
                        className="ph-no-capture block w-fit max-w-full"
                        data-attr="trace-person-link"
                    >
                        <PersonDisplay {...toPersonDisplayProps(person)} withIcon="sm" />
                    </span>
                </span>
            )}
        </TraceCellValue>
    )
}
