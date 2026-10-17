import { SandboxHourlyPrice } from './SandboxHourlyPrice'

// A null price means a local docker kernel, which has no rate to quote.
export const sandboxStartMessage = (hourlyPrice: number | null): string | JSX.Element => {
    if (hourlyPrice == null) {
        return 'Starting a compute sandbox. The cell will run once it’s ready.'
    }
    return (
        <>
            Starting a compute sandbox at <SandboxHourlyPrice value={hourlyPrice} /> while it runs. Change its size in
            the kernel panel.
        </>
    )
}
