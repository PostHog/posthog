import { LemonBanner } from '@posthog/lemon-ui'

export interface HomeRangeTooLongProps {
    detail: string
}

export function HomeRangeTooLong({ detail }: HomeRangeTooLongProps): JSX.Element {
    return <LemonBanner type="info">{detail}</LemonBanner>
}
