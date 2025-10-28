import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { sidePanelDocsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelDocsLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import {
    VALID_NATIVE_MARKETING_SOURCES,
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
} from '../../logic/utils'

interface AddIntegrationButtonProps {
    onIntegrationSelect?: (integrationId: string) => void
}

export function AddIntegrationButton({ onIntegrationSelect }: AddIntegrationButtonProps = {}): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    const [showPopover, setShowPopover] = useState(false)
    const [pendingNavigation, setPendingNavigation] = useState<{
        integrationId: string
        onIntegrationSelect?: (integrationId: string) => void
    } | null>(null)

    const groupedIntegrations = {
        native: VALID_NATIVE_MARKETING_SOURCES,
        external: VALID_NON_NATIVE_MARKETING_SOURCES,
        'self-managed': VALID_SELF_MANAGED_MARKETING_SOURCES,
    }

    // Watch for when the docs iframe is ready and trigger pending navigation
    useEffect(() => {
        if (!pendingNavigation) {
            return
        }

        const checkIframeReady = (): void => {
            const docsLogic = sidePanelDocsLogic.findMounted()
            const iframeReady = docsLogic?.values?.iframeReady

            if (iframeReady && pendingNavigation) {
                // Docs are loaded, trigger navigation
                if (pendingNavigation.onIntegrationSelect) {
                    pendingNavigation.onIntegrationSelect(pendingNavigation.integrationId)
                } else {
                    router.actions.push(urls.dataWarehouseSourceNew(pendingNavigation.integrationId))
                }
                setShowPopover(false)
                setPendingNavigation(null)
            }
        }

        // Check immediately and then set up interval to watch for changes
        checkIframeReady()
        const interval = setInterval(checkIframeReady, 100)

        return () => clearInterval(interval)
    }, [pendingNavigation])

    const handleIntegrateClick = (integrationId: string, sourceType: 'native' | 'external' | 'self-managed'): void => {
        // Open docs in side panel
        let docFragment = ''
        if (sourceType === 'native') {
            docFragment = '#native-sources'
        } else if (sourceType === 'external') {
            docFragment = '#data-warehouse-sources'
        } else if (sourceType === 'self-managed') {
            docFragment = '#self-managed-sources'
        }
        openSidePanel(SidePanelTab.Docs, `/docs/web-analytics/marketing-analytics${docFragment}`)

        // If panel wasn't open, wait for docs to load before navigating otherwise
        // there will be a race condition where the panel is opened, then docs are loaded
        // and the dw source will fail to load because of the url params + fragments conflict
        if (!sidePanelOpen) {
            setPendingNavigation({ integrationId, onIntegrationSelect })
            return
        }

        // Panel was already open, navigate immediately
        if (onIntegrationSelect) {
            onIntegrationSelect(integrationId)
        } else {
            router.actions.push(urls.dataWarehouseSourceNew(integrationId))
        }
        setShowPopover(false)
    }

    const renderIntegrationGroup = (type: string, integrations: string[], title: string): JSX.Element | null => {
        if (integrations.length === 0) {
            return null
        }

        return (
            <div key={type}>
                <div className="px-2 py-1 text-xs font-medium text-muted-foreground">{title}</div>
                {integrations.map((integrationId) => (
                    <LemonButton
                        key={integrationId}
                        fullWidth
                        size="small"
                        onClick={() =>
                            handleIntegrateClick(integrationId, type as 'native' | 'external' | 'self-managed')
                        }
                        className="justify-start"
                    >
                        <span className="flex items-center gap-2">
                            <DataWarehouseSourceIcon type={integrationId} size="xsmall" disableTooltip />
                            <span className="flex flex-col items-start">
                                <span className="font-medium">{integrationId}</span>
                            </span>
                        </span>
                    </LemonButton>
                ))}
            </div>
        )
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={showPopover}
            matchWidth={false}
            actionable
            onVisibilityChange={setShowPopover}
            overlay={
                <div className="max-w-80 space-y-px p-1">
                    <div className="px-2 py-1 text-xs text-muted-foreground font-bold">Connect new data source</div>
                    {renderIntegrationGroup('native', groupedIntegrations.native, 'Native integrations')}
                    {renderIntegrationGroup('external', groupedIntegrations.external, 'External sources')}
                    {renderIntegrationGroup(
                        'self-managed',
                        groupedIntegrations['self-managed'],
                        'Self-managed sources'
                    )}
                </div>
            }
        >
            <LemonButton type="primary" size="small" icon={<IconPlusSmall />} data-attr="add-integration">
                Add source
            </LemonButton>
        </LemonDropdown>
    )
}
