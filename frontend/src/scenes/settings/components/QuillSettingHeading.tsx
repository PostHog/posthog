import { Button, Heading, Text } from '@posthog/quill'

import { QuillSupportedPlatforms } from 'lib/components/SupportedPlatforms/QuillSupportedPlatforms'
import { IconLink } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { Setting } from '../types'

export function QuillSettingHeading({
    setting,
    showTitle,
    linkTo,
    onLinkClick,
}: {
    setting: Setting
    showTitle: boolean
    /** Only the full settings scene links to a single setting. */
    linkTo?: string
    onLinkClick: () => void
}): JSX.Element | null {
    const hasTitle = showTitle && !!setting.title

    if (!hasTitle && !setting.description) {
        return null
    }

    return (
        <div className="flex flex-col gap-1 mb-4">
            {hasTitle && (
                <Heading
                    size="base"
                    render={
                        <h2
                            id={setting.id}
                            className="flex gap-1 items-center m-0 scroll-mt-[calc(var(--scene-layout-header-height)+var(--spacing)*4)]"
                        />
                    }
                >
                    {setting.title}
                    {linkTo && (
                        <Button
                            size="icon-sm"
                            aria-label="Link to this setting"
                            tooltip="Link to this setting"
                            nativeButton={false}
                            render={
                                <LinkPrimitive
                                    to={linkTo}
                                    onClick={(e) => {
                                        onLinkClick()
                                        e.preventDefault()
                                    }}
                                />
                            }
                        >
                            <IconLink />
                        </Button>
                    )}
                    {setting.platformSupport && <QuillSupportedPlatforms config={setting.platformSupport} />}
                </Heading>
            )}
            {setting.description && (
                <Text size="xs" variant="muted" render={<p className="m-0 max-w-160" />}>
                    {setting.description}
                    {setting.docsUrl && (
                        <>
                            &nbsp;
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={setting.docsUrl} target="_blank" />}
                                data-attr={`settings-docs-link-${setting.id}`}
                            >
                                Docs
                            </Button>
                        </>
                    )}
                </Text>
            )}
        </div>
    )
}
