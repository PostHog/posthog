import { Badge, Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger, Text } from '@posthog/quill'

import { EmailConfigStatus } from '../../scenes/settings/supportSettingsLogic'
import { QuillAddEmailForm } from '../QuillAddEmailForm/QuillAddEmailForm'
import { QuillEmailConfigContent } from '../QuillEmailConfigContent/QuillEmailConfigContent'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'

export function QuillEmailSection({ emailConfigs }: { emailConfigs: EmailConfigStatus[] }): JSX.Element {
    return (
        <QuillSettingsSubsection
            title="Email channel"
            description="Receive customer emails as support tickets and reply directly from PostHog. Set up forwarding and verify your domain to enable two-way email."
        >
            <div className="flex flex-col gap-2">
                {emailConfigs.map((config: EmailConfigStatus) => (
                    <Collapsible key={config.id} className="rounded-md border border-border p-2">
                        <CollapsibleHeader className="flex-wrap">
                            <CollapsibleTrigger iconOnly>{`Show details for ${config.from_email}`}</CollapsibleTrigger>
                            <Text size="xs" weight="semibold" render={<span className="min-w-0 truncate" />}>
                                {config.from_email}
                            </Text>
                            {config.from_name && (
                                <Text size="xs" variant="muted" render={<span className="min-w-0 truncate" />}>
                                    {`(${config.from_name})`}
                                </Text>
                            )}
                            {config.is_default && <Badge>Primary</Badge>}
                            {config.domain_verified ? (
                                <Badge variant="success">Verified</Badge>
                            ) : (
                                <Badge variant="warning">Unverified</Badge>
                            )}
                        </CollapsibleHeader>
                        <CollapsibleContent className="pt-3">
                            <QuillEmailConfigContent config={config} />
                        </CollapsibleContent>
                    </Collapsible>
                ))}
                <QuillAddEmailForm />
            </div>
        </QuillSettingsSubsection>
    )
}
