import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

interface OpenURLButtonProps {
    url: string | null
    disabledReason?: string
}

export const OpenURLButton = ({ url, disabledReason }: OpenURLButtonProps): JSX.Element => {
    if (!url && !disabledReason) {
        return <></>
    }

    if (!url) {
        return (
            <LemonButton
                disabledReason={disabledReason}
                icon={<IconExternal />}
                type="tertiary"
                size="xsmall"
                tooltip="Open URL"
                className="no-underline"
            />
        )
    }

    return (
        <LemonButton
            to={url}
            icon={<IconExternal />}
            type="tertiary"
            size="xsmall"
            tooltip="Open URL"
            className="no-underline"
            targetBlank
            hideExternalLinkIcon={true}
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
            }}
        />
    )
}
