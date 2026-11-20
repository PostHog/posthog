import { useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    Label,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'

import { QuillCopyField } from './QuillCopyField'
import { verifiedDomainsLogic } from './verifiedDomainsLogic'

export function QuillConfigureSCIMModal({
    showToken,
    onClose,
    onToggleScim,
    onRegenerateToken,
}: {
    showToken: boolean
    onClose: () => void
    onToggleScim: () => void
    onRegenerateToken: () => void
}): JSX.Element {
    const { configureSCIMModalId, scimConfig, scimConfigLoading } = useValues(verifiedDomainsLogic)

    return (
        <Dialog open={!!configureSCIMModalId} onOpenChange={(open) => !open && onClose()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Configure SCIM provisioning</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {scimConfigLoading ? (
                        <Skeleton className="h-40 w-full" />
                    ) : (
                        <div className="flex flex-col gap-4">
                            <Text size="xs" render={<p className="m-0" />}>
                                <Button
                                    variant="link"
                                    size="inline"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to="https://posthog.com/docs/data/sso#setting-up-scim"
                                            target="_blank"
                                        />
                                    }
                                >
                                    Read the docs
                                </Button>
                            </Text>

                            <QuillSettingSwitch
                                label="Enable SCIM"
                                checked={scimConfig.scim_enabled ?? false}
                                onCheckedChange={onToggleScim}
                            />

                            {scimConfig.scim_enabled && (
                                <>
                                    <QuillCopyField
                                        label="SCIM Base URL"
                                        value={scimConfig.scim_base_url || ''}
                                        description="SCIM base URL"
                                    />

                                    {showToken ? (
                                        <div className="flex flex-col gap-2">
                                            <QuillCopyField
                                                label="Bearer Token"
                                                value={scimConfig.scim_bearer_token || ''}
                                                description="Bearer token"
                                                sensitive
                                            />
                                            <Item tone="warning" size="sm">
                                                <ItemContent>
                                                    <ItemDescription>
                                                        Save this token, it will only be shown once.
                                                    </ItemDescription>
                                                </ItemContent>
                                            </Item>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col items-start gap-2">
                                            <Label>Bearer Token</Label>
                                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                The bearer token is only displayed once when generated.
                                            </Text>
                                            <Button variant="outline" onClick={onRegenerateToken}>
                                                <IconRefresh />
                                                Regenerate token
                                            </Button>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
