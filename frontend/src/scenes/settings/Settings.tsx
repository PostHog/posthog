import './Settings.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React from 'react'

import { IconChevronDown, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonButtonProps, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'
import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconLink } from 'lib/lemon-ui/icons'
import { inStorybookTestRunner } from 'lib/utils'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SearchResultGroup } from './settingsLogic'
import { settingsLogic } from './settingsLogic'
import { SettingId, SettingLevelId, SettingSectionId, SettingsLogicProps } from './types'

export interface SettingOption {
    key: string
    content: JSX.Element
    items?: SettingOption[]
}

export function Settings({
    hideSections = false,
    handleLocally = false,
    ...props
}: SettingsLogicProps & { hideSections?: boolean; handleLocally?: boolean }): JSX.Element {
    const {
        selectedSectionId,
        selectedSection,
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
        setSearchTerm,
        toggleLevelCollapse,
        toggleGroupCollapse,
        navigateToSetting,
    } = useActions(settingsLogic(props))
    const { currentTeam } = useValues(teamLogic)

    const { ref, size } = useResizeBreakpoints(
        {
            0: 'small',
            700: 'medium',
        },
        {
            initialSize: 'medium',
        }
    )

    const isCompact = !inStorybookTestRunner() && size === 'small'

    const showOptions = isCompact ? isCompactNavigationOpen : true
    const settingsInSidebar = props.sectionId && !!selectedSetting

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
                  const isDangerZone = id.endsWith('-danger-zone')

                  return {
                      key: section.id,
                      content: (
                          <OptionButton
                              key={id}
                              to={to ?? urls.settings(id)}
                              handleLocally={handleLocally}
                              active={selectedSectionId === id}
                              isLink={!!to}
                              isDanger={isDangerZone}
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
              const levelItems: SettingOption[] = !isCollapsed
                  ? [
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
                                    content: (
                                        <OptionButton
                                            handleLocally={handleLocally}
                                            active={false}
                                            onClick={() => toggleGroupCollapse(groupKey)}
                                            sideIcon={
                                                <IconChevronDown
                                                    className={clsx(
                                                        'w-4 h-4 transition-transform',
                                                        isGroupCollapsed && '-rotate-90'
                                                    )}
                                                />
                                            }
                                        >
                                            {section.group}
                                        </OptionButton>
                                    ),
                                    items: !isGroupCollapsed ? sectionsInGroup.map(buildSectionOption) : [],
                                },
                            ]
                        }),
                        // Danger zone always at the bottom
                        ...dangerZoneSections.map(buildSectionOption),
                    ]
                  : []

              return {
                  key: level,
                  content: (
                      <OptionButton
                          handleLocally={handleLocally}
                          active={false}
                          onClick={() => toggleLevelCollapse(level)}
                          sideIcon={
                              <IconChevronDown
                                  className={clsx('w-4 h-4 transition-transform', isCollapsed && '-rotate-90')}
                              />
                          }
                      >
                          <span className="text-secondary">{SettingLevelNames[level]}</span>
                      </OptionButton>
                  ),
                  items: levelItems,
              }
          })

    const compactNavigationContent: JSX.Element = settingsInSidebar ? (
        <>{selectedSetting.title}</>
    ) : (
        <>
            {SettingLevelNames[selectedLevel]}
            {selectedSection ? <> / {selectedSection.title}</> : null}
        </>
    )

    return (
        <div className={clsx('Settings flex items-start', isCompact && 'Settings--compact')} ref={ref}>
            {hideSections ? null : (
                <>
                    {showOptions ? (
                        <div className="Settings__sections">
                            {!settingsInSidebar && (
                                <div className="Settings__sections__search">
                                    <LemonInput
                                        type="search"
                                        placeholder="Search settings..."
                                        value={searchTerm}
                                        onChange={setSearchTerm}
                                        size="small"
                                        fullWidth
                                    />
                                </div>
                            )}
                            <div className="Settings__sections__list">
                                {isSearching && !settingsInSidebar ? (
                                    <SearchResults
                                        results={searchResults}
                                        onSelect={navigateToSetting}
                                        handleLocally={handleLocally}
                                    />
                                ) : (
                                    <OptionGroup options={options} />
                                )}
                            </div>
                        </div>
                    ) : (
                        <LemonButton fullWidth sideIcon={<IconChevronRight />} onClick={() => openCompactNavigation()}>
                            {compactNavigationContent}
                        </LemonButton>
                    )}
                    {isCompact ? <LemonDivider /> : null}
                </>
            )}

            <AuthenticationAreaComponent>
                <div className="flex-1 w-full min-w-0 min-h-screen space-y-2 self-start">
                    {!hideSections && selectedLevel === 'project' && (
                        <LemonBanner type="info">
                            These settings only apply to the current project{' '}
                            {currentTeam?.name ? (
                                <>
                                    (<b>{currentTeam.name}</b>)
                                </>
                            ) : null}
                            .
                        </LemonBanner>
                    )}

                    <SettingsRenderer {...props} handleLocally={handleLocally} />
                </div>
            </AuthenticationAreaComponent>
        </div>
    )
}

function SearchResults({
    results,
    onSelect,
    handleLocally,
}: {
    results: SearchResultGroup[]
    onSelect: (sectionId: SettingSectionId, settingId: SettingId) => void
    handleLocally: boolean
}): JSX.Element {
    if (results.length === 0) {
        return <div className="text-muted text-sm p-2">No settings found</div>
    }

    return (
        <ul className="gap-y-px">
            {results.map((group) => (
                <React.Fragment key={group.sectionId}>
                    <li className="text-muted text-xs font-semibold uppercase pt-2 pb-1 px-2">
                        {group.sectionTitle}
                        <span className="text-muted-alt ml-1">({SettingLevelNames[group.level]})</span>
                    </li>
                    {group.results.map((result) => (
                        <li key={`${result.sectionId}-${result.settingId}`}>
                            <LemonButton
                                fullWidth
                                size="small"
                                onClick={
                                    handleLocally
                                        ? (e) => {
                                              onSelect(result.sectionId, result.settingId)
                                              e.preventDefault()
                                          }
                                        : () => onSelect(result.sectionId, result.settingId)
                                }
                                data-attr={`settings-search-result-${result.settingId}`}
                            >
                                {result.settingTitle}
                            </LemonButton>
                        </li>
                    ))}
                </React.Fragment>
            ))}
        </ul>
    )
}

function SettingsRenderer(props: SettingsLogicProps & { handleLocally: boolean }): JSX.Element {
    const { settings: allSettings, selectedLevel, selectedSectionId, selectedSetting } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    const settingsInSidebar = !!selectedSetting && !!props.sectionId

    const settings = settingsInSidebar ? [selectedSetting] : allSettings

    return (
        <div className="flex flex-col gap-y-8 pb-[30vh]">
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

                        {x.component}
                    </div>
                ))
            ) : (
                <NotFound object="setting" />
            )}
        </div>
    )
}

const depthMap: Record<number, string> = {
    1: 'pl-4',
    2: 'pl-8',
}

const OptionGroup = ({ options, depth = 0 }: { options: SettingOption[]; depth?: number }): JSX.Element => {
    return (
        <ul className="gap-y-px">
            {options.map((option) => (
                <React.Fragment key={option.key}>
                    <li className={clsx(depthMap[depth])}>{option.content}</li>
                    {option.items ? <OptionGroup options={option.items} depth={depth + 1} /> : null}
                </React.Fragment>
            ))}
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
    isDanger = false,
    sideIcon,
    disabledReason,
    'data-attr': dataAttr,
}: Pick<LemonButtonProps, 'to' | 'children' | 'active' | 'disabledReason'> & {
    handleLocally: boolean
    onClick: () => void
    isLink?: boolean
    isDanger?: boolean
    sideIcon?: JSX.Element
    'data-attr'?: string
}): JSX.Element => {
    return (
        <LemonButton
            to={to}
            onClick={
                handleLocally
                    ? (e) => {
                          onClick()
                          e.preventDefault()
                      }
                    : undefined
            }
            size="small"
            sideIcon={isLink ? <IconExternal /> : sideIcon}
            fullWidth
            active={active}
            status={isDanger ? 'danger' : undefined}
            disabledReason={disabledReason}
            data-attr={dataAttr}
        >
            {children}
        </LemonButton>
    )
}

export const SettingLevelNames: Record<SettingLevelId, string> = {
    environment: 'Environment',
    project: 'Project',
    organization: 'Organization',
    user: 'Account',
} as const
