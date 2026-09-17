import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconApps, IconFolder } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { classicEmbedContext } from './classicEmbedContext'
import { desktopCatalogLogic, desktopObjectHref } from './desktopCatalogLogic'

export function DesktopNavigation(): JSX.Element {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { objectTypes, tools, objectType } = useValues(desktopCatalogLogic)
    const { location } = useValues(router)
    const isTools = classicEmbedContext?.section === 'tools'
    const isLanding = location.pathname.endsWith('/home')
    const title = isTools ? 'Tools' : 'Library'

    return (
        <nav className="flex flex-col gap-1 overflow-y-auto p-2" aria-label={`${title} navigation`}>
            {!isLayoutNavCollapsed && <span className="text-xs text-secondary px-2 py-2">{title}</span>}
            <LemonButton
                fullWidth
                type="tertiary"
                active={isLanding && !objectType}
                icon={isTools ? <IconApps /> : <IconFolder />}
                tooltip={isLayoutNavCollapsed ? (isTools ? 'All tools' : 'All objects') : undefined}
                to={urls.projectHomepage()}
            >
                {!isLayoutNavCollapsed && (isTools ? 'All tools' : 'All objects')}
            </LemonButton>
            {isTools
                ? tools.map((item) => (
                      <LemonButton
                          key={item.path}
                          fullWidth
                          type="tertiary"
                          to={desktopObjectHref(item)}
                          icon={iconForType(item.iconType ?? (item.type as FileSystemIconType))}
                          active={
                              !!item.href &&
                              location.pathname.startsWith(desktopObjectHref(item)?.split('?')[0] ?? '\0')
                          }
                          tooltip={isLayoutNavCollapsed ? item.displayLabel || item.path : undefined}
                      >
                          {!isLayoutNavCollapsed && <span className="truncate">{item.displayLabel || item.path}</span>}
                      </LemonButton>
                  ))
                : objectTypes.map((item) => (
                      <LemonButton
                          key={item.value}
                          fullWidth
                          type="tertiary"
                          to={`${urls.projectHomepage()}?library_type=${encodeURIComponent(item.value)}`}
                          icon={iconForType(item.value as FileSystemIconType)}
                          active={isLanding && objectType === item.value}
                          tooltip={isLayoutNavCollapsed ? item.label : undefined}
                      >
                          {!isLayoutNavCollapsed && item.label}
                      </LemonButton>
                  ))}
        </nav>
    )
}
