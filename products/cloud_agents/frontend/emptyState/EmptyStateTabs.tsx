import { CloudAgentsTabs } from '../components/CloudAgentsTabs'

/** Keeps Presets, Usage and Settings reachable while the empty state replaces the runs scene. */
export function EmptyStateTabs(): JSX.Element {
    return <CloudAgentsTabs activeTab="runs" />
}
