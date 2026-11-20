import { IconGear } from '@posthog/icons'
import { Card, Text } from '@posthog/quill'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { IntegrationSettingsModal } from './IntegrationSettingsModal'

function settingsSummary(mappingsCount: number, sourcesCount: number, matchField: string | undefined): string {
    const parts = [
        mappingsCount > 0 && `${mappingsCount} mapping${mappingsCount !== 1 ? 's' : ''}`,
        sourcesCount > 0 && `${sourcesCount} source${sourcesCount !== 1 ? 's' : ''}`,
        matchField,
    ].filter(Boolean)

    return parts.length > 0 ? parts.join(', ') : 'Default configuration'
}

export function QuillIntegrationSettingsCard({
    integrationName,
    mappingsCount,
    sourcesCount,
    fieldPreferenceMatchField,
    isModalOpen,
    onModalOpenChange,
}: {
    integrationName: string
    mappingsCount: number
    sourcesCount: number
    fieldPreferenceMatchField: string | undefined
    isModalOpen: boolean
    onModalOpenChange: (open: boolean) => void
}): JSX.Element {
    return (
        <>
            <Card size="sm" className="w-40 p-0">
                <button
                    type="button"
                    className="group relative flex w-full flex-col items-center gap-2 rounded-lg p-4 text-center hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={() => onModalOpenChange(true)}
                >
                    <IconGear className="absolute top-2 right-2 size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100 motion-reduce:transition-none" />
                    <SourceIcon type={integrationName} size="medium" disableTooltip />
                    <Text size="sm" weight="semibold" render={<span />}>
                        {integrationName}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />}>
                        {settingsSummary(mappingsCount, sourcesCount, fieldPreferenceMatchField)}
                    </Text>
                </button>
            </Card>
            <IntegrationSettingsModal
                integrationName={integrationName}
                isOpen={isModalOpen}
                onClose={() => onModalOpenChange(false)}
            />
        </>
    )
}
