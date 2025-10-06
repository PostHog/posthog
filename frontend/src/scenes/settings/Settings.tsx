import './Settings.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import React from 'react'

import { IconChevronDown, IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonButtonProps, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/components/AccessControlAction'
import { NotFound } from 'lib/components/NotFound'
import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight, IconLink } from 'lib/lemon-ui/icons'
import { inStorybookTestRunner } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { settingsLogic } from './settingsLogic'
import { SettingLevelId, SettingsLogicProps } from './types'

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
        filteredLevels,
        filteredSections,
        collapsedLevels,
    } = useValues(settingsLogic(props))
    const { selectSection, selectLevel, selectSetting, openCompactNavigation, setSearchTerm, toggleLevelCollapse } =
        useActions(settingsLogic(props))
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
                  >
                      {s.title}
                  </OptionButton>
              ),
          }))
        : filteredLevels.map((level) => {
              const levelSections = filteredSections.filter((x) => x.level === level)
              const isCollapsed = collapsedLevels[level]
              const hasItems = levelSections.length > 0

              return {
                  key: level,
                  content: (
                      <OptionButton
                          handleLocally={handleLocally}
                          active={selectedLevel === level && !selectedSectionId}
                          onClick={() => {
                              if (hasItems) {
                                  toggleLevelCollapse(level)
                              } else {
                                  selectLevel(level)
                              }
                          }}
                          sideIcon={hasItems ? isCollapsed ? <IconChevronRight /> : <IconChevronDown /> : undefined}
                      >
                          <span className="text-secondary">{SettingLevelNames[level]}</span>
                      </OptionButton>
                  ),
                  items: !isCollapsed
                      ? levelSections.map((section) => {
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
                                    >
                                        {section.title}
                                    </OptionButton>
                                ),
                            }
                        })
                      : [],
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
        <div className={clsx('Settings flex', isCompact && 'Settings--compact')} ref={ref}>
            {hideSections ? null : (
                <>
                    {showOptions ? (
                        <div className="Settings__sections">
                            {!settingsInSidebar && (
                                <LemonInput
                                    type="search"
                                    placeholder="Search settings..."
                                    value={searchTerm}
                                    onChange={setSearchTerm}
                                    size="small"
                                    fullWidth
                                    className="mb-2"
                                />
                            )}
                            <OptionGroup options={options} />
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
                <div className="flex-1 w-full min-w-0 space-y-2">
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

function SettingsRenderer(props: SettingsLogicProps & { handleLocally: boolean }): JSX.Element {
    const { settings: allSettings, selectedLevel, selectedSectionId, selectedSetting } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    const settingsInSidebar = !!selectedSetting && !!props.sectionId

    const settings = settingsInSidebar ? [selectedSetting] : allSettings

    return (
        <div className="flex flex-col gap-y-8">
            {settings.length ? (
                settings.map((x) => (
                    <div key={x.id} className="relative last:mb-4">
                        {!settingsInSidebar && (
                            <h2 id={x.id} className="flex gap-2 items-center">
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
                            </h2>
                        )}
                        {x.description && <p className="max-w-160">{x.description}</p>}

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
}

const OptionGroup = ({ options, depth = 0 }: { options: SettingOption[]; depth?: number }): JSX.Element => {
    return (
        <ul className="gap-y-px">
            {options.map((option) => (
                <React.Fragment key={option.key}>
                    <li className={depthMap[depth]}>{option.content}</li>
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
    sideIcon,
    disabledReason,
}: Pick<LemonButtonProps, 'to' | 'children' | 'active' | 'disabledReason'> & {
    handleLocally: boolean
    onClick: () => void
    isLink?: boolean
    sideIcon?: JSX.Element
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
            disabledReason={disabledReason}
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
