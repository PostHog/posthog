import { LemonLabel } from '~/lib/lemon-ui/LemonLabel'

export function LemonBreakdownByLabel({ info }: { info: string }): JSX.Element {
    return <LemonLabel info={info}>Breakdown by</LemonLabel>
}
