import { LemonDivider } from '@posthog/lemon-ui'

export function SceneDivider(): JSX.Element | null {
    return <LemonDivider className="scene-divider -mx-4 w-[calc(100%+var(--spacing)*8)]" />
}
