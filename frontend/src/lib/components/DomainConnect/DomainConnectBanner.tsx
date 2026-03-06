import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { DomainConnectProviderName } from '~/queries/schema/schema-general'

import cloudflareLogo from './assets/cloudflare.svg'
import { DomainConnectLogicProps, DomainConnectProvider, domainConnectLogic } from './domainConnectLogic'

const PROVIDER_LOGOS: Record<DomainConnectProviderName, string> = {
    [DomainConnectProviderName.Cloudflare]: cloudflareLogo,
}

function ProviderLogo({ name }: { name: DomainConnectProviderName }): JSX.Element | null {
    const logoUrl = PROVIDER_LOGOS[name]
    if (!logoUrl) {
        return null
    }
    return <img src={logoUrl} alt={name} className="size-4 rounded-sm" />
}

/**
 * Shared banner component for Domain Connect automatic DNS configuration.
 *
 * Three states:
 * 1. Auto-detected provider -> "Configure automatically via {provider}" button
 * 2. No auto-detection, but providers are available -> manual "I use {provider}" buttons
 * 3. No providers -> renders nothing
 *
 * Mount with different `logicKey` props to avoid state sharing between instances.
 */
export function DomainConnectBanner(props: DomainConnectLogicProps & { className?: string }): JSX.Element | null {
    const logic = domainConnectLogic(props)
    const { autoDetected, providerName, availableProviders, domainConnectInfoLoading } = useValues(logic)
    const { openDomainConnect } = useActions(logic)

    if (domainConnectInfoLoading) {
        return null
    }

    if (autoDetected && providerName) {
        return (
            <LemonBanner type="info" className={props.className}>
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                        <ProviderLogo name={providerName} />
                        <span>
                            Your DNS is managed by <strong>{providerName}</strong>, which supports automatic
                            configuration.
                        </span>
                    </div>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => openDomainConnect()}
                        icon={<IconExternal />}
                        targetBlank
                    >
                        Configure automatically
                    </LemonButton>
                </div>
            </LemonBanner>
        )
    }

    if (availableProviders.length > 0) {
        return (
            <LemonBanner type="info" className={props.className}>
                <div className="space-y-2">
                    <span>
                        If your DNS provider supports automatic configuration, you can set up these records with a
                        single click.
                    </span>
                    <div className="flex gap-2 flex-wrap">
                        {availableProviders.map((provider: DomainConnectProvider) => (
                            <LemonButton
                                key={provider.endpoint}
                                type="secondary"
                                size="small"
                                onClick={() => openDomainConnect(provider.endpoint)}
                                icon={<ProviderLogo name={provider.name} />}
                                sideIcon={<IconExternal />}
                            >
                                I use {provider.name}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            </LemonBanner>
        )
    }

    return null
}
