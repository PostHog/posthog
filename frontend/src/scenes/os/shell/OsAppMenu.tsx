import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { osAppSlug } from '../store/osAppCatalog'
import { osWindowsLogic } from '../windows/osWindowsLogic'
import { osMenuBarLogic } from './osMenuBarLogic'
import { osShellLogic } from './osShellLogic'

/**
 * The menu of the app in the focused window, like the application menu on macOS: the app's name, and a
 * menu of its pages. A window that no app claims gets its title and the window items. Nothing renders
 * while no window has focus.
 */
export function OsAppMenu(): JSX.Element | null {
    const { appMenu, focusedWindow } = useValues(osMenuBarLogic)
    const { openAppPage } = useActions(osMenuBarLogic)
    const { openApp } = useActions(osShellLogic)
    const { minimizeWindow, closeWindow } = useActions(osWindowsLogic)
    const [open, setOpen] = useState(false)
    const focusedWindowId = focusedWindow?.id

    // A click into a window goes to its frame, which the menu's outside-click check cannot see. The page
    // loses focus instead, and the menu closes. It also closes when another window comes to the front.
    useEffect(() => {
        const close = (): void => setOpen(false)
        window.addEventListener('blur', close)
        return () => window.removeEventListener('blur', close)
    }, [])
    useEffect(() => setOpen(false), [focusedWindowId])

    if (!focusedWindow) {
        return null
    }

    const windowItems: LemonMenuItems = [
        {
            items: [
                appMenu && {
                    label: 'New window',
                    onClick: () => openApp(appMenu.app.href, appMenu.app.name, undefined, true),
                    'data-attr': 'os-app-menu-new-window',
                },
                {
                    label: 'Minimize window',
                    onClick: () => minimizeWindow(focusedWindow.id),
                    'data-attr': 'os-app-menu-minimize',
                },
                {
                    label: 'Close window',
                    onClick: () => closeWindow(focusedWindow.id),
                    'data-attr': 'os-app-menu-close',
                },
            ],
        },
    ]
    const items: LemonMenuItems = appMenu
        ? [
              {
                  items: appMenu.pages.map((page) => ({
                      label:
                          page === appMenu.activePage ? (
                              <span>
                                  {page.label}
                                  <span className="sr-only">, current page</span>
                              </span>
                          ) : (
                              page.label
                          ),
                      active: page === appMenu.activePage,
                      onClick: () => openAppPage(page.href),
                      'data-attr': `os-app-menu-page-${osAppSlug(page.label)}`,
                  })),
              },
              appMenu.newItems.length > 0 && {
                  items: [
                      {
                          label: 'New',
                          placement: 'right-start',
                          'data-attr': 'os-app-menu-new',
                          items: appMenu.newItems.map((item) => ({
                              label: item.label,
                              onClick: () => openAppPage(item.href),
                              'data-attr': `os-app-menu-new-${osAppSlug(item.label)}`,
                          })),
                      },
                  ],
              },
              appMenu.relatedApps.length > 0 && {
                  title: 'Related apps',
                  items: appMenu.relatedApps.map((related) => ({
                      label: related.label,
                      onClick: () => openApp(related.href, related.label),
                      'data-attr': `os-app-menu-related-${osAppSlug(related.label)}`,
                  })),
              },
              ...windowItems,
          ]
        : windowItems
    const name = appMenu?.app.name ?? focusedWindow.title

    return (
        <LemonMenu items={items} placement="bottom-start" visible={open} onVisibilityChange={setOpen}>
            <button
                type="button"
                className="OsShell__menu-trigger font-bold min-w-0"
                aria-label={`${name} menu`}
                data-attr="os-app-menu"
            >
                <span className="truncate">{name}</span>
            </button>
        </LemonMenu>
    )
}
