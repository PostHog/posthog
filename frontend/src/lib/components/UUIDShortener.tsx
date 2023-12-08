import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function truncateUuid(uuid: string): string {
    // Simple function to truncate a UUID. Useful for more simple displaying but should always be made clear it is truncated.
    return uuid
        .split('-')
        .map((x) => x.slice(0, 2))
        .join('')
}

export function UUIDShortener({ uuid, clickToCopy = false }: { uuid: string; clickToCopy?: boolean }): JSX.Element {
    return (
        <Tooltip
            title={
                <>
                    <span className="whitespace-nowrap">{uuid}</span>
                    {clickToCopy && (
                        <>
                            <br />
                            Double click to copy
                        </>
                    )}
                </>
            }
        >
            <span onDoubleClick={clickToCopy ? () => copyToClipboard(uuid) : undefined} title={uuid}>
                {truncateUuid(uuid)}...
            </span>
        </Tooltip>
    )
}
