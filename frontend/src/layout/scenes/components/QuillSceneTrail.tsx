import { ReactNode } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillSceneStaticName } from './QuillSceneStaticName'

export interface QuillSceneTrailParent {
    name: ReactNode
    path?: string
}

// Every offset in the trail lives here. Each one cancels padding so the gaps read evenly and nothing moves when the
// trail changes shape: link buttons and the current crumb pad 8px, and `QuillSceneName`'s box pads its text by 7px
// (6px plus a 1px border).
const SLASH = 'shrink-0 text-subtle-foreground'
const SLASH_AFTER_LINK = cn(SLASH, 'me-1')
const SLASH_BEFORE_NAME = cn(SLASH, '-ms-1 -me-[3px]')
const TITLE_ICON = '-me-1.5 flex size-4 shrink-0 items-center justify-center text-sm [&_svg]:size-4'
const LINK_ICON = '-me-[3px] flex size-4 shrink-0 items-center justify-center [&_svg]:size-4'
const CRUMB = '-ms-2'
// Matches the link button's box, so a static parent sits where a link parent would.
const STATIC_PARENT =
    '-ms-2 inline-flex h-7 min-w-0 max-w-48 shrink-0 items-center gap-2 px-2 text-[length:var(--text-ui,0.8125rem)] font-medium text-muted-foreground'

export interface QuillSceneTrailCurrent {
    name: ReactNode
    description?: ReactNode
}

export interface QuillSceneTrailProps {
    /** A crumb before the parent, such as the hidden sidebar's pane. It must render as a link-sized button. */
    lead?: ReactNode
    parent?: QuillSceneTrailParent
    icon?: ReactNode
    /** Puts the icon before the scene name instead of on the parent crumb. */
    iconLeadsName?: boolean
    /** The scene itself as the last crumb, for a name nobody can rename. Without it, an editable name follows the trail. */
    current?: QuillSceneTrailCurrent
}

export function QuillSceneTrail({ lead, parent, icon, iconLeadsName, current }: QuillSceneTrailProps): JSX.Element {
    const parentIcon = parent && !iconLeadsName ? icon : undefined
    const nameIcon = parentIcon ? undefined : icon
    return (
        <>
            {lead && (
                <>
                    {lead}
                    {/* The lead drops to an icon in a narrow scene, and a slash after a bare icon reads as noise. */}
                    <span className={cn(SLASH_AFTER_LINK, '@max-xl/main-content:hidden')} aria-hidden>
                        /
                    </span>
                </>
            )}
            {parent ? (
                <>
                    {parent.path ? (
                        <Button
                            className="-ms-2 min-w-0 max-w-48 text-muted-foreground"
                            render={<LinkPrimitive to={parent.path} />}
                            data-attr="scene-title-breadcrumb-back"
                        >
                            {parentIcon && (
                                <span className={LINK_ICON} aria-hidden>
                                    {parentIcon}
                                </span>
                            )}
                            <span className="truncate">{parent.name}</span>
                        </Button>
                    ) : (
                        <span className={STATIC_PARENT}>
                            {parentIcon && (
                                <span className={LINK_ICON} aria-hidden>
                                    {parentIcon}
                                </span>
                            )}
                            <span className="truncate">{parent.name}</span>
                        </span>
                    )}
                    <span className={current ? SLASH_AFTER_LINK : SLASH_BEFORE_NAME} aria-hidden>
                        /
                    </span>
                </>
            ) : null}
            {nameIcon && !current && (
                <span className={TITLE_ICON} aria-hidden>
                    {nameIcon}
                </span>
            )}
            {current && (
                <QuillSceneStaticName
                    name={current.name}
                    icon={nameIcon}
                    description={current.description}
                    className={CRUMB}
                />
            )}
        </>
    )
}
