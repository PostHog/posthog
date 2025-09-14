import { LemonButton } from "@posthog/lemon-ui"
import { router } from "kea-router"

export function NamedQuery(): JSX.Element {
    return (
        <LemonButton
        size="small"
        onClick={() => {
            router.actions.push('/embedded-analytics/named-queries')
        }}
        type="primary"
    >
        Create named query
    </LemonButton>
    )    
}
