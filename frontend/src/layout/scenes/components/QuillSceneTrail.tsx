import { useValues } from 'kea'
import { ReactNode } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { TodaySidebarBreadcrumb } from '~/layout/today/TodaySidebarBreadcrumb'

export interface QuillSceneTrailParent {
    name: ReactNode
    path: string
}

// Every offset in the trail lives here. Each one cancels padding so the gaps read evenly and nothing moves when the
// trail changes shape: link buttons pad 8px, and `QuillSceneName`'s box pads its text by 7px (6px plus a 1px border).
const SLASH = 'shrink-0 text-muted-foreground'
const SLASH_AFTER_LINK = cn(SLASH, '-ms-1 me-1')
const SLASH_BEFORE_NAME = cn(SLASH, '-ms-1 -me-[3px]')
const TITLE_ICON = '-me-1.5 flex size-4 shrink-0 items-center justify-center text-sm [&_svg]:size-4'
const LINK_ICON = '-me-[3px] flex size-4 shrink-0 items-center justify-center [&_svg]:size-4'

export function QuillSceneTrail({ parent, icon }: { parent?: QuillSceneTrailParent; icon?: ReactNode }): JSX.Element {
    const { sidebarBreadcrumbShown } = useValues(todayShellLogic)

    return (
        <>
            {sidebarBreadcrumbShown && (
                <>
                    <TodaySidebarBreadcrumb />
                    <span className={SLASH_AFTER_LINK} aria-hidden>
                        /
                    </span>
                </>
            )}
            {parent ? (
                <>
                    <Button
                        className="-ms-2 min-w-0 max-w-48 text-muted-foreground"
                        render={<LinkPrimitive to={parent.path} />}
                        data-attr="scene-title-breadcrumb-back"
                    >
                        {icon && (
                            <span className={LINK_ICON} aria-hidden>
                                {icon}
                            </span>
                        )}
                        <span className="truncate">{parent.name}</span>
                    </Button>
                    <span className={SLASH_BEFORE_NAME} aria-hidden>
                        /
                    </span>
                </>
            ) : (
                icon && (
                    <span className={TITLE_ICON} aria-hidden>
                        {icon}
                    </span>
                )
            )}
        </>
    )
}
