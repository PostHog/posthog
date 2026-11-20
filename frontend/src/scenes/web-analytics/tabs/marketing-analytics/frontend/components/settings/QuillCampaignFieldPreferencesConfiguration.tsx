import {
    Heading,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { CampaignFieldPreference, MatchField } from '~/queries/schema/schema-general'

const MATCH_FIELD_OPTIONS = [
    { value: MatchField.CAMPAIGN_NAME, label: 'Campaign name' },
    { value: MatchField.CAMPAIGN_ID, label: 'Campaign ID' },
]

export function QuillCampaignFieldPreferencesConfiguration({
    sourceFilter,
    integrationsToShow,
    getMatchField,
    onPreferenceChange,
    restrictedReason,
}: {
    sourceFilter?: string
    integrationsToShow: string[]
    getMatchField: (integration: string) => CampaignFieldPreference['match_field']
    onPreferenceChange: (integration: string, matchField: CampaignFieldPreference['match_field']) => void
    restrictedReason: string | null
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Campaign field preferences
            </Heading>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Choose whether to match <code>utm_campaign</code> values against campaign names or campaign IDs.
                Defaults to campaign name if not configured.
            </Text>

            <Table>
                <TableHeader>
                    <TableRow>
                        {!sourceFilter && <TableHead>Integration</TableHead>}
                        <TableHead>Match utm_campaign by</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {integrationsToShow.map((integration) => (
                        <TableRow key={integration}>
                            {!sourceFilter && <TableCell className="font-medium">{integration}</TableCell>}
                            <TableCell>
                                <ToggleGroup
                                    variant="outline"
                                    aria-label={`Match utm_campaign by for ${integration}`}
                                    value={[getMatchField(integration)]}
                                    onValueChange={(next: string[]) => {
                                        const picked = next[0] as CampaignFieldPreference['match_field'] | undefined
                                        if (picked) {
                                            onPreferenceChange(integration, picked)
                                        }
                                    }}
                                >
                                    {MATCH_FIELD_OPTIONS.map((option) => (
                                        <ToggleGroupItem
                                            key={option.value}
                                            value={option.value}
                                            disabledReason={restrictedReason}
                                        >
                                            {option.label}
                                        </ToggleGroupItem>
                                    ))}
                                </ToggleGroup>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </section>
    )
}
