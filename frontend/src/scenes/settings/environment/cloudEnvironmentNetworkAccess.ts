import { SandboxEnvironmentNetworkAccessLevelEnumApi } from 'products/tasks/frontend/generated/api.schemas'

export const NETWORK_ACCESS_COPY: Record<
    SandboxEnvironmentNetworkAccessLevelEnumApi,
    { label: string; description: string }
> = {
    [SandboxEnvironmentNetworkAccessLevelEnumApi.Trusted]: {
        label: 'Trusted',
        description: 'Downloads packages from verified sources, such as GitHub, npm, and PyPI.',
    },
    [SandboxEnvironmentNetworkAccessLevelEnumApi.Full]: {
        label: 'Full',
        description: 'Unrestricted internet access.',
    },
    [SandboxEnvironmentNetworkAccessLevelEnumApi.Custom]: {
        label: 'Custom',
        description: 'Only the domains you list.',
    },
}

export function networkAccessLabel(level: string): string {
    return NETWORK_ACCESS_COPY[level as SandboxEnvironmentNetworkAccessLevelEnumApi]?.label ?? level
}
