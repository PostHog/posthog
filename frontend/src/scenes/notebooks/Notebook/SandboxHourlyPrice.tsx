export const formatHourlyPrice = (value: number): string => `$${value.toFixed(2)} / h`

export type SandboxHourlyPriceProps = {
    /** USD per hour. */
    value: number
}

export const SandboxHourlyPrice = ({ value }: SandboxHourlyPriceProps): JSX.Element => {
    return (
        <span translate="no">
            <s className="text-muted font-normal">{formatHourlyPrice(value)}</s> <span>{formatHourlyPrice(0)}</span>
        </span>
    )
}
