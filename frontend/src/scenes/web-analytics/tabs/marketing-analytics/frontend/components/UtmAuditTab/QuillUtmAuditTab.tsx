import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import type { HealthTab } from '../../logic/utmAuditLogic'
import { QuillOptionSelect } from '../common/QuillOptionSelect'
import { IntegrationSettingsModal } from '../settings/IntegrationSettingsModal'
import { QuillUtmAuditSettingsTab } from './QuillUtmAuditSettingsTab'

export function QuillUtmAuditTab({
    loading,
    failed,
    onReload,
    sourceFilterValue,
    sourceFilterOptions,
    onSourceFilterChange,
    stats,
    activeTab,
    onTabChange,
    campaignContent,
    sourceContent,
    integrationFilter,
}: {
    loading: boolean
    failed: boolean
    onReload: () => void
    sourceFilterValue: string
    sourceFilterOptions: { value: string; label: string }[]
    onSourceFilterChange: (value: string) => void
    stats: { label: string; value: number; alert?: boolean }[]
    activeTab: HealthTab
    onTabChange: (tab: HealthTab) => void
    campaignContent: JSX.Element
    sourceContent: JSX.Element
    integrationFilter?: string
}): JSX.Element {
    const { integrationSettingsModal } = useValues(marketingAnalyticsSettingsLogic)
    const { closeIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    return (
        <div className="@container mt-4 mb-8 flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Button variant="outline" onClick={onReload} loading={loading}>
                    Reload
                </Button>
                <QuillOptionSelect
                    value={sourceFilterValue}
                    onChange={onSourceFilterChange}
                    options={sourceFilterOptions}
                    ariaLabel="Integration"
                />
            </div>

            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                PostHog uses UTM parameters (utm_source, utm_campaign) from your pageview events to connect website
                traffic back to your ad platform campaigns. This connection powers marketing conversion goal{' '}
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-xs"
                                className="align-middle"
                                aria-label="About marketing conversion goals"
                            />
                        }
                    >
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">
                        Conversion goals are events or actions you define in settings (e.g. purchase, sign up) that are
                        tracked and attributed to your marketing campaigns.
                    </TooltipContent>
                </Tooltip>{' '}
                attribution. If campaigns aren't linked to UTM events, their conversion goals won't be tracked. The best
                fix is to update your UTM parameters directly in your ad platform campaigns. If that's not possible, you
                can create a manual mapping here to bridge the gap.
            </Text>

            {failed ? (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Failed to load integration health data. This may be because the feature is not yet enabled
                            for your account.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            ) : (
                <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                    {stats.map((stat) => (
                        <Card key={stat.label} size="sm">
                            <CardContent className="flex flex-col gap-1">
                                <Text size="xs" variant="muted" render={<div />}>
                                    {stat.label}
                                </Text>
                                {loading ? (
                                    <Skeleton className="h-7 w-12" />
                                ) : (
                                    <Text
                                        size="lg"
                                        weight="semibold"
                                        className={cn('tabular-nums', stat.alert && 'text-warning-foreground')}
                                        render={<div />}
                                    >
                                        {stat.value.toLocaleString()}
                                    </Text>
                                )}
                            </CardContent>
                        </Card>
                    ))}
                </div>
            )}

            <Tabs value={activeTab} onValueChange={(value) => onTabChange(value as HealthTab)}>
                <TabsList variant="line">
                    <TabsTrigger value="campaign">Campaigns</TabsTrigger>
                    <TabsTrigger value="source">Sources</TabsTrigger>
                    <TabsTrigger value="settings">UTM preferences</TabsTrigger>
                </TabsList>
                <TabsContent value="campaign">{campaignContent}</TabsContent>
                <TabsContent value="source">{sourceContent}</TabsContent>
                <TabsContent value="settings">
                    <QuillUtmAuditSettingsTab integrationFilter={integrationFilter} />
                </TabsContent>
            </Tabs>

            {integrationSettingsModal.integration && (
                <IntegrationSettingsModal
                    integrationName={integrationSettingsModal.integration}
                    isOpen={integrationSettingsModal.isOpen}
                    onClose={closeIntegrationSettingsModal}
                    initialTab={integrationSettingsModal.initialTab}
                    initialUtmValue={integrationSettingsModal.initialUtmValue}
                    initialCampaignName={integrationSettingsModal.initialCampaignName}
                />
            )}
        </div>
    )
}
