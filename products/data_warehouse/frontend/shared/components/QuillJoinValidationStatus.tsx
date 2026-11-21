import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, Spinner, Text } from '@posthog/quill'

import { openInAppSupport } from 'lib/components/Support/openInAppSupport'

import { viewLinkLogic } from '../logics/viewLinkLogic'
import { QuillJoinMatchPreview } from './QuillJoinMatchPreview'

export function QuillJoinValidationStatus(): JSX.Element | null {
    const { joinValidation, keyTypeMismatchWarning } = useValues(viewLinkLogic)

    return (
        <div className="flex flex-col gap-2 empty:hidden">
            {keyTypeMismatchWarning && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>{keyTypeMismatchWarning}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {joinValidation.status === 'validating' && (
                <div className="flex items-center gap-2">
                    <Spinner />
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        Validating join...
                    </Text>
                </div>
            )}
            {joinValidation.status === 'valid' && (
                <>
                    <div className="flex items-center gap-2 text-success-foreground">
                        <IconCheckCircle />
                        <Text size="xs" render={<span className="m-0 text-success-foreground" />}>
                            Join is valid
                        </Text>
                    </div>
                    <QuillJoinMatchPreview />
                </>
            )}
            {joinValidation.status === 'valid' && joinValidation.msg && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>{joinValidation.msg}</ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {joinValidation.status === 'error' && (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>{joinValidation.msg || 'Could not validate the join.'}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={() => openInAppSupport('join-modal-validation-error')}>
                            Get help
                        </Button>
                    </ItemActions>
                </Item>
            )}
        </div>
    )
}
