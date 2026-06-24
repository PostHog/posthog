import { IconEye } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export function ForYouBadge(): JSX.Element {
    return (
        <Tooltip title="You are a suggested reviewer">
            <LemonTag size="small" type="warning" className="gap-1 cursor-help select-none">
                <IconEye className="shrink-0" />
                For you
            </LemonTag>
        </Tooltip>
    )
}
