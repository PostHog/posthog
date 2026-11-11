import { HighlightedName } from './HighlightedName'

export function ConnectTitle({ lead, clientName }: { lead: string; clientName: string }): JSX.Element {
    return (
        <>
            <span>{lead} </span>
            <HighlightedName>{clientName}</HighlightedName>
        </>
    )
}
