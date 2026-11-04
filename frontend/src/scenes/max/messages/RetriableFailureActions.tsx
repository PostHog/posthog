import { useActions } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useQuillThread } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../maxThreadLogic'

export function RetriableFailureActions(): JSX.Element {
    const { retryLastMessage } = useActions(maxThreadLogic)

    if (useQuillThread()) {
        return (
            <div>
                <Button variant="outline" size="sm" onClick={() => retryLastMessage()}>
                    <IconRefresh />
                    Try again
                </Button>
            </div>
        )
    }

    return (
        <LemonButton
            icon={<IconRefresh />}
            type="tertiary"
            size="xsmall"
            tooltip="Try again"
            onClick={() => retryLastMessage()}
            className="ml-1"
        >
            Try again
        </LemonButton>
    )
}
