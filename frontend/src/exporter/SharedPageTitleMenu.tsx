import { useCallback, useState } from 'react'

import { IconChevronDown, IconCopy, IconLaptop, IconRefresh } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { useCloseOnWindowBlur } from './useCloseOnWindowBlur'

const NOUN_LABEL = { canvas: 'Canvas', file: 'File' } as const

/** The title of a shared page, opening a menu with where it came from and where a viewer can take it. */
export function SharedPageTitleMenu({
    title,
    noun,
    isCreator,
    teamName,
    updatedAt,
    openPath,
    forkUrl,
}: {
    title: string
    noun: 'canvas' | 'file'
    isCreator?: boolean
    teamName?: string
    /** When the version the link shows was last published. */
    updatedAt?: string | null
    /** In-app path to the original, for viewers who may open it. */
    openPath?: string | null
    /** Where a viewer gets their own copy; null when the owner has not allowed that. */
    forkUrl?: string | null
}): JSX.Element {
    const [open, setOpen] = useState(false)
    useCloseOnWindowBlur(
        open,
        useCallback(() => setOpen(false), [])
    )

    const byline = isCreator
        ? `${NOUN_LABEL[noun]} by you`
        : teamName
          ? `${NOUN_LABEL[noun]} from ${teamName}`
          : `Shared ${noun}`
    const items: LemonMenuItems = [
        {
            title: (
                <div className="flex flex-col gap-0.5 px-2 py-1 font-normal normal-case text-muted">
                    <span>{byline}</span>
                    {updatedAt && <span>Updated {dayjs(updatedAt).fromNow()}</span>}
                </div>
            ),
            items: [
                openPath
                    ? {
                          label: 'Open in PostHog Desktop',
                          icon: <IconLaptop />,
                          to: openPath,
                          disableClientSideRouting: true,
                          'data-attr': 'shared-page-open-in-desktop',
                      }
                    : null,
                forkUrl
                    ? {
                          label: 'Duplicate',
                          icon: <IconCopy />,
                          to: forkUrl,
                          disableClientSideRouting: true,
                          'data-attr': 'shared-page-open-copy',
                      }
                    : null,
                {
                    label: 'Refresh',
                    icon: <IconRefresh />,
                    onClick: () => window.location.reload(),
                    'data-attr': 'shared-page-refresh',
                },
            ],
        },
    ]

    return (
        <LemonMenu items={items} visible={open} onVisibilityChange={setOpen} placement="bottom-start">
            {/* The trigger is not the popover's DOM reference, so without the opt-out its pointerdown dismisses
                the menu and the click that follows reopens it. */}
            <LemonButton
                type="tertiary"
                size="small"
                sideIcon={<IconChevronDown />}
                className={`${CLICK_OUTSIDE_BLOCK_CLASS} min-w-0`}
                data-attr="shared-page-title"
            >
                <span className="truncate font-semibold">{title}</span>
            </LemonButton>
        </LemonMenu>
    )
}
