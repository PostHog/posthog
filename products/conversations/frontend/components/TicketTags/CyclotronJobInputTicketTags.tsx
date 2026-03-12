import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { TicketTags } from '.'

export default function CyclotronJobInputTicketTags({ value, onChange }: CustomInputRendererProps): JSX.Element {
    return <TicketTags tags={value ?? []} onChange={onChange} className="justify-start" />
}
