import { TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode } from '~/queries/schema'

export interface TaxonomicFilterReplayGroupProps {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue) => void
    metadataSource?: AnyDataNode
}

export function TaxonomicFilterReplayGroup({ onChange }: TaxonomicFilterReplayGroupProps): JSX.Element {
    return (
        <div className="px-2">
            <div onClick={() => onChange('duration')}>Duration</div>
            <div onClick={() => onChange('console_logs')}>Console logs</div>
        </div>
    )
}
