import './Settings.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React from 'react'

import { IconExternal, IconList } from '@posthog/icons'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'
import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { IconLink } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    cn,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Combobox,
    ComboboxCollection,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    Drawer,
    DrawerContent,
    DrawerTitle,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { inStorybookTestRunner } from 'lib/utils'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { ErrorBoundary } from '~/layout/ErrorBoundary'

import { SearchResult, settingsLogic } from './settingsLogic'
import { SettingLevelId, SettingsLogicProps } from './types'

export interface SettingOption {
    key: string
    content?: JSX.Element
    items?: SettingOption[]
    collapsible?: {
        label: React.ReactNode
        open: boolean
        onOpenChange: (open: boolean) => void
    }
}

export function Settings({
    hideSections = false,
    handleLocally = false,
    headerSlot,
    ...props
}: SettingsLogicProps & {
    hideSections?: boolean
    handleLocally?: boolean
    headerSlot?: JSX.Element | null
}): JSX.Element {
    const {
        selectedSectionId,
        selectedLevel,
        selectedSettingId,
        selectedSetting,
        settings,
        isCompactNavigationOpen,
        searchTerm,
        isSearching,
        searchResults,
        filteredLevels,
        filteredSections,
        collapsedLevels,
        collapsedGroups,
    } = useValues(settingsLogic(props))
    const {
        selectSection,
        selectSetting,
        openCompactNavigation,
        closeCompactNavigation,
        setSearchTerm,
        toggleLevelCollapse,
        toggleGroupCollapse,
        navigateToSetting,
    } = useActions(settingsLogic(props))

    // Tailwind `md` breakpoint (768px). Matches `screens.md` in common/tailwind/tailwind.config.js.
    const [isViewportCompact, setIsViewportCompact] = React.useState(() => {
        if (typeof window === 'undefined') {
            return false
        }
        return window.matchMedia('(max-width: 767px)').matches
    })
    React.useEffect(() => {
        const mql = window.matchMedia('(max-width: 767px)')
        const update = (e: MediaQueryListEvent | MediaQueryList): void => setIsViewportCompact(e.matches)
        update(mql)
        mql.addEventListener('change', update)
        return () => mql.removeEventListener('change', update)
    }, [])

    const isCompact = !inStorybookTestRunner() && isViewportCompact

    // The full settings scene fills the scene area, so its nav can be viewport-fixed.
    // Embeds (replay settings, error tracking config, side panel, modal) place the nav
    // in normal flow instead, so it sits beside the content rather than overlapping.
    const isFullScene = props.logicKey === 'settingsScene'

    const settingsInSidebar = props.sectionId && !!selectedSetting

    const searchItems: SearchResult[] = React.useMemo(
        () => searchResults.flatMap((group) => group.results),
        [searchResults]
    )

    // Track the visual viewport so the mobile drawer shrinks above the on-screen
    // keyboard (`dvh` units don't account for the keyboard) — keeps the list scrollable.
    // Only needed in compact mode, where the Drawer is used.
    const [visualViewportHeight, setVisualViewportHeight] = React.useState<number | null>(null)
    React.useEffect(() => {
        const vv = window.visualViewport
        if (!isCompact || !vv) {
            return
        }
        const update = (): void => setVisualViewportHeight(vv.height)
        update()
        vv.addEventListener('resize', update)
        return () => vv.removeEventListener('resize', update)
    }, [isCompact])

    // Scroll the active item into view in the nav, on load and whenever the selected
    // section changes. Delayed so any auto-expanded collapsible has finished animating.
    React.useEffect(() => {
        if (isSearching || !selectedSectionId) {
            return
        }
        const timer = setTimeout(() => {
            document
                .querySelector(`[data-attr="settings-menu-item-${selectedSectionId}"]`)
                ?.scrollIntoView({ block: 'nearest' })
        }, 250)
        return () => clearTimeout(timer)
    }, [selectedSectionId, isSearching])

    // Currently environment and project settings do not require periodic re-authentication,
    // though this is likely to change (see https://github.com/posthog/posthog/pull/22421).
    // In the meantime, we don't want a needless re-authentication modal:
    const AuthenticationAreaComponent =
        selectedLevel !== 'environment' && selectedLevel !== 'project'
            ? TimeSensitiveAuthenticationArea
            : React.Fragment

    const options: SettingOption[] = settingsInSidebar
        ? settings.map((s) => ({
              key: s.id,
              content: (
                  <OptionButton
                      active={selectedSettingId === s.id}
                      handleLocally={handleLocally}
                      onClick={() => selectSetting(s.id)}
                      data-attr={`settings-menu-item-${s.id}`}
                  >
                      {s.title}
                  </OptionButton>
              ),
          }))
        : filteredLevels.map((level) => {
              const levelSections = filteredSections.filter((x) => x.level === level)
              const isCollapsed = collapsedLevels[level]

              // Separate danger zone sections (always rendered last)
              const dangerZoneSections = levelSections.filter((s) => s.id.endsWith('-danger-zone'))
              const nonDangerSections = levelSections.filter((s) => !s.id.endsWith('-danger-zone'))

              // Build section option helper
              const buildSectionOption = (section: (typeof levelSections)[0]): SettingOption => {
                  const { id, to, accessControl } = section

                  return {
                      key: section.id,
                      content: (
                          <OptionButton
                              key={id}
                              to={to ?? urls.settings(id)}
                              handleLocally={handleLocally}
                              active={selectedSectionId === id}
                              isLink={!!to}
                              onClick={() => {
                                  if (to) {
                                      router.actions.push(to)
                                  } else {
                                      selectSection(id, level)
                                  }
                              }}
                              disabledReason={
                                  accessControl
                                      ? getAccessControlDisabledReason(
                                            accessControl.resourceType,
                                            accessControl.minimumAccessLevel
                                        )
                                      : undefined
                              }
                              data-attr={`settings-menu-item-${id}`}
                          >
                              {section.title}
                          </OptionButton>
                      ),
                  }
              }

              // Build items in SETTINGS_MAP order, rendering groups when we first encounter them
              const renderedGroups = new Set<string>()
              const levelItems: SettingOption[] = [
                  ...nonDangerSections.flatMap((section) => {
                      // Ungrouped section - render directly
                      if (!section.group) {
                          return [buildSectionOption(section)]
                      }

                      // Grouped section - render entire group when we first see it
                      if (renderedGroups.has(section.group)) {
                          return [] // Already rendered this group
                      }

                      renderedGroups.add(section.group)
                      const groupKey = `${level}-${section.group}`
                      const isGroupCollapsed = collapsedGroups[groupKey]
                      const sectionsInGroup = nonDangerSections.filter((s) => s.group === section.group)

                      return [
                          {
                              key: groupKey,
                              collapsible: {
                                  label: section.group,
                                  open: !isGroupCollapsed,
                                  onOpenChange: () => toggleGroupCollapse(groupKey),
                              },
                              items: sectionsInGroup.map(buildSectionOption),
                          },
                      ]
                  }),
                  // Danger zone always at the bottom
                  ...dangerZoneSections.map(buildSectionOption),
              ]

              return {
                  key: level,
                  collapsible: {
                      label: SettingLevelNames[level],
                      open: !isCollapsed,
                      onOpenChange: () => toggleLevelCollapse(level),
                  },
                  items: levelItems,
              }
          })

    const navContent: JSX.Element = settingsInSidebar ? (
        <div className="flex-1 min-h-0 overflow-y-auto scroll-mask-y-4">
            <OptionGroup options={options} />
        </div>
    ) : (
        <Combobox
            items={searchItems}
            filter={null}
            inline
            defaultOpen
            highlightItemOnHover
            inputValue={searchTerm}
            onInputValueChange={(value: string) => setSearchTerm(value)}
            itemToStringValue={(item: SearchResult | null) => item?.settingTitle ?? ''}
            onValueChange={(item: SearchResult | null) => {
                if (item) {
                    navigateToSetting(item.sectionId, item.settingId)
                }
            }}
        >
            <div className="p-1 shrink-0 border-b">
                <ComboboxInput
                    className="w-full"
                    placeholder="Search settings..."
                    showTrigger={false}
                    showClear={!!searchTerm}
                    aria-label="Search settings"
                />
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto scroll-mask-y-4 scroll-py-8">
                {isSearching ? (
                    <ComboboxList className="max-h-none overflow-visible px-1">
                        {searchResults.length === 0 ? (
                            <div className="text-muted text-sm p-2">No settings found</div>
                        ) : (
                            searchResults.map((group) => (
                                <ComboboxGroup key={group.sectionId} items={group.results} className="mb-2">
                                    <ComboboxLabel className="text-tertiary p-0 pl-1">
                                        {group.sectionTitle}
                                        <span className="text-tertiary-alt ml-1">
                                            ({SettingLevelNames[group.level]})
                                        </span>
                                    </ComboboxLabel>
                                    <ComboboxCollection>
                                        {(result: SearchResult) => (
                                            <ComboboxItem
                                                key={`${result.sectionId}-${result.settingId}`}
                                                value={result}
                                                data-attr={`settings-search-result-${result.settingId}`}
                                                render={<Button left>{result.settingTitle}</Button>}
                                            />
                                        )}
                                    </ComboboxCollection>
                                </ComboboxGroup>
                            ))
                        )}
                    </ComboboxList>
                ) : (
                    <OptionGroup options={options} />
                )}
            </div>
        </Combobox>
    )

    return (
        <div className={clsx('Settings flex items-start', isCompact && 'Settings--compact')}>
            {hideSections ? null : isCompact ? (
                <>
                    <Button variant="outline" left className="w-full" onClick={() => openCompactNavigation()}>
                        <IconList className="stroke-2 size-4 mr-1" />{' '}
                        <span className="flex-1 truncate text-left font-semibold text-base">Settings menu</span>
                    </Button>
                    <Drawer
                        swipeDirection="left"
                        open={isCompactNavigationOpen}
                        onOpenChange={(open) => (open ? openCompactNavigation() : closeCompactNavigation())}
                    >
                        <DrawerContent data-quill>
                            <DrawerTitle className="sr-only">Settings navigation</DrawerTitle>
                            {/* Pin the height to the visual viewport (minus the drawer's 1rem
                                padding) so the search stays put, the list scrolls within, and
                                the panel shrinks above the on-screen keyboard. */}
                            <div
                                className="flex flex-col min-h-0"
                                style={{
                                    height:
                                        visualViewportHeight != null
                                            ? `${visualViewportHeight - 16}px`
                                            : 'calc(100dvh - 1rem)',
                                }}
                            >
                                {navContent}
                            </div>
                        </DrawerContent>
                    </Drawer>
                    <LemonDivider />
                </>
            ) : (
                <div
                    data-quill
                    className={clsx(
                        'border rounded w-[var(--settings-nav-width)] flex flex-col',
                        isFullScene
                            ? 'fixed top-(--scene-padding) bottom-(--scene-padding)'
                            : 'sticky top-(--scene-layout-header-height) self-start max-h-[calc(100dvh-var(--scene-layout-header-height)-var(--scene-padding))]'
                    )}
                >
                    {navContent}
                </div>
            )}

            <div
                className={clsx(
                    'flex-1 w-full min-w-0 self-start pb-32',
                    isFullScene && !hideSections && !isCompact && 'pl-[calc(var(--settings-nav-width)+2rem)]'
                )}
            >
                <AuthenticationAreaComponent>
                    <div className="space-y-2">
                        {headerSlot}
                        <SettingsRenderer {...props} handleLocally={handleLocally} />
                    </div>
                </AuthenticationAreaComponent>
            </div>
        </div>
    )
}

function SettingsRenderer(props: SettingsLogicProps & { handleLocally: boolean }): JSX.Element {
    const { settings: allSettings, selectedLevel, selectedSectionId, selectedSetting } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    const settingsInSidebar = !!selectedSetting && !!props.sectionId

    const settings = settingsInSidebar ? [selectedSetting] : allSettings

    return (
        <div className="flex flex-col gap-y-8">
            {settings.length ? (
                settings.map((x, index) => (
                    <div key={`${x.id}-${index}`} className="relative last:mb-4">
                        {!settingsInSidebar && x.title && (
                            <h2 id={x.id} className="flex gap-2 items-center text-base font-semibold mb-0">
                                {x.title}
                                {props.logicKey === 'settingsScene' && (
                                    <LemonButton
                                        icon={<IconLink />}
                                        size="small"
                                        to={urls.settings(selectedSectionId ?? selectedLevel, x.id)}
                                        onClick={(e) => {
                                            selectSetting(x.id)
                                            e.preventDefault()
                                        }}
                                    />
                                )}
                                {x.platformSupport && <SupportedPlatforms config={x.platformSupport} />}
                            </h2>
                        )}
                        {x.description && (
                            <p className="max-w-160 text-sm text-secondary mb-4">
                                {x.description}
                                {x.docsUrl && (
                                    <>
                                        &nbsp;
                                        <Link to={x.docsUrl} target="_blank" data-attr={`settings-docs-link-${x.id}`}>
                                            Docs
                                        </Link>
                                    </>
                                )}
                            </p>
                        )}

                        <ErrorBoundary>{x.component}</ErrorBoundary>
                    </div>
                ))
            ) : (
                <NotFound object="setting" />
            )}
        </div>
    )
}

const depthMap: Record<number, string> = {
    1: 'pl-4.5',
    2: 'pl-5.5 -ml-3',
}

const OptionGroup = ({ options, depth = 0 }: { options: SettingOption[]; depth?: number }): JSX.Element => {
    return (
        <ul className={cn('gap-y-px px-1', depth === 0 && 'p-1')}>
            {options.map((option) =>
                option.collapsible ? (
                    <li key={option.key} className={clsx(depthMap[depth])}>
                        <Collapsible
                            open={option.collapsible.open}
                            onOpenChange={option.collapsible.onOpenChange}
                            className="bg-transparent!"
                            variant="folder"
                        >
                            <CollapsibleTrigger
                                render={<Button left className="w-full" />}
                                className={cn(depth !== 0 && '-ml-2 w-[calc(100%+var(--spacing)*2)]')}
                            >
                                <span className="flex-1 truncate text-left font-semibold">
                                    {option.collapsible.label}
                                </span>
                            </CollapsibleTrigger>
                            <CollapsibleContent className="pl-0 pr-1 py-1">
                                {option.items ? <OptionGroup options={option.items} depth={depth + 1} /> : null}
                            </CollapsibleContent>
                        </Collapsible>
                    </li>
                ) : (
                    <React.Fragment key={option.key}>
                        <li className={clsx(depthMap[depth])}>{option.content}</li>
                        {option.items ? <OptionGroup options={option.items} depth={depth + 1} /> : null}
                    </React.Fragment>
                )
            )}
        </ul>
    )
}

const OptionButton = ({
    to,
    active,
    onClick,
    children,
    handleLocally,
    isLink = false,
    sideIcon,
    disabledReason,
    'data-attr': dataAttr,
}: {
    to?: string
    children: React.ReactNode
    active?: boolean
    disabledReason?: string | null | false
    handleLocally: boolean
    onClick: () => void
    isLink?: boolean
    sideIcon?: JSX.Element
    'data-attr'?: string
}): JSX.Element => {
    const isDisabled = !!disabledReason

    const button = (
        <Button
            left
            className="w-full font-normal"
            disabled={isDisabled}
            aria-selected={active || undefined}
            data-attr={dataAttr}
            onClick={
                handleLocally
                    ? (e: React.MouseEvent<HTMLButtonElement>) => {
                          onClick()
                          e.preventDefault()
                      }
                    : to || isDisabled
                      ? undefined
                      : () => onClick()
            }
            {...(to && !isDisabled
                ? {
                      render: <LinkPrimitive to={to} className={cn('no-underline', active && 'font-bold')} />,
                  }
                : {})}
        >
            <span className="flex-1 truncate text-left">{children}</span>
            {isLink ? <IconExternal /> : sideIcon}
        </Button>
    )

    if (isDisabled) {
        return (
            <Tooltip>
                <TooltipTrigger render={button} />
                <TooltipContent>{disabledReason}</TooltipContent>
            </Tooltip>
        )
    }

    return button
}

export const SettingLevelNames: Record<SettingLevelId, string> = {
    environment: 'Environment',
    project: 'Project',
    organization: 'Organization',
    user: 'Account',
} as const
