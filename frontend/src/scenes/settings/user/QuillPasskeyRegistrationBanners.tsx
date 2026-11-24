import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemMedia, Spinner } from '@posthog/quill'

import { passkeySettingsLogic } from './passkeySettingsLogic'

export function QuillPasskeyRegistrationBanners(): JSX.Element | null {
    const { registrationStep, error } = useValues(passkeySettingsLogic)
    const { clearError } = useActions(passkeySettingsLogic)

    if (!error && registrationStep !== 'complete' && registrationStep !== 'verifying') {
        return null
    }

    return (
        <>
            {error && (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>{error}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button size="icon-sm" aria-label="Dismiss" tooltip="Dismiss" onClick={clearError}>
                            <IconX />
                        </Button>
                    </ItemActions>
                </Item>
            )}

            {registrationStep === 'complete' && (
                <Item tone="success" size="sm">
                    <ItemContent>
                        <ItemDescription>Passkey added and verified successfully!</ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {registrationStep === 'verifying' && (
                <Item tone="info" size="sm">
                    <ItemMedia>
                        <Spinner />
                    </ItemMedia>
                    <ItemContent>
                        <ItemDescription>Please verify your passkey to complete registration...</ItemDescription>
                    </ItemContent>
                </Item>
            )}
        </>
    )
}
