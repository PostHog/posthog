export const formatHourlyPrice = (value: number): string => `$${value.toFixed(2)} / h`

export type SandboxHourlyPriceProps = {
    /** USD per hour. */
    value: number
    isFree: boolean
}

export const SandboxHourlyPrice = ({ value, isFree }: SandboxHourlyPriceProps): JSX.Element => {
    if (!isFree) {
        return <span translate="no">{formatHourlyPrice(value)}</span>
    }
    return (
        <span translate="no">
            <s className="text-muted font-normal">{formatHourlyPrice(value)}</s> <span>{formatHourlyPrice(0)}</span>
        </span>
    )
}
