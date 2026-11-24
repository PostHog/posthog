import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { CampaignFieldPreferencesConfiguration } from './CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from './CampaignNameMappingsConfiguration'
import { CustomSourceMappingsConfiguration } from './CustomSourceMappingsConfiguration'
import type { IntegrationSettingsTab } from './IntegrationSettingsModal'

export function QuillIntegrationSettingsModal({
    integrationName,
    isOpen,
    onClose,
    activeTab,
    onTabChange,
    initialUtmValue,
    initialCampaignName,
}: {
    integrationName: string
    isOpen: boolean
    onClose: () => void
    activeTab: IntegrationSettingsTab
    onTabChange: (tab: IntegrationSettingsTab) => void
    initialUtmValue?: string
    initialCampaignName?: string
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-3">
                        <SourceIcon type={integrationName} size="small" disableTooltip />
                        <span>{integrationName} settings</span>
                    </DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <Tabs value={activeTab} onValueChange={(tab) => onTabChange(tab as IntegrationSettingsTab)}>
                        <TabsList variant="line">
                            <TabsTrigger value="field">Match field</TabsTrigger>
                            <TabsTrigger value="mappings">Campaign mappings</TabsTrigger>
                            <TabsTrigger value="sources">Custom sources</TabsTrigger>
                        </TabsList>
                        <TabsContent value="field" className="pt-3">
                            <div className="flex flex-col gap-3">
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Select whether to match campaigns using the campaign name or campaign ID. This
                                    determines how we link your UTM parameters back to the {integrationName} data. If
                                    your UTM campaign values don't match either,{' '}
                                    <Button variant="link" size="inline" onClick={() => onTabChange('mappings')}>
                                        configure manual mappings
                                    </Button>
                                    .
                                </Text>
                                <CampaignFieldPreferencesConfiguration sourceFilter={integrationName} />
                            </div>
                        </TabsContent>
                        <TabsContent value="mappings" className="pt-3">
                            <div className="flex flex-col gap-3">
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    If you're using custom UTM campaign values that don't match your {integrationName}{' '}
                                    campaign names or IDs, add mappings here. This lets you manually link arbitrary UTM
                                    campaign tags back to the correct campaign in {integrationName} based on your{' '}
                                    <Button variant="link" size="inline" onClick={() => onTabChange('field')}>
                                        selected match field
                                    </Button>
                                    .
                                </Text>
                                <CampaignNameMappingsConfiguration
                                    sourceFilter={integrationName}
                                    compact
                                    initialUtmValue={initialUtmValue}
                                    initialCampaignName={initialCampaignName}
                                />
                            </div>
                        </TabsContent>
                        <TabsContent value="sources" className="pt-3">
                            <div className="flex flex-col gap-3">
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    We automatically recognize common UTM sources for {integrationName}, but if you use
                                    custom source values in your campaigns, add them here so we can properly attribute
                                    the traffic.
                                </Text>
                                <CustomSourceMappingsConfiguration
                                    sourceFilter={integrationName}
                                    initialUtmValue={initialUtmValue}
                                />
                            </div>
                        </TabsContent>
                    </Tabs>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
