import './Settings.scss'

import { LemonBanner, LemonButton, LemonButtonProps, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { TimeSensitiveAuthenticationArea } from 'lib/components/TimeSensitiveAuthentication/TimeSensitiveAuthentication'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight, IconLink } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, inStorybookTestRunner } from 'lib/utils'
import React from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { settingsLogic } from './settingsLogic'
import { SettingsLogicProps } from './types'

export interface SettingOption {
    key: string
    content: JSX.Element
    items?: SettingOption[]
}

export function Settings({
    hideSections = false,
    ...props
}: SettingsLogicProps & { hideSections?: boolean }): JSX.Element {
    const {
        selectedSectionId,
        selectedSection,
        selectedLevel,
        selectedSettingId,
        sections,
        settings,
        isCompactNavigationOpen,
        levels,
    } = useValues(settingsLogic(props))
    const { selectSection, selectLevel, selectSetting, openCompactNavigation } = useActions(settingsLogic(props))
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

    // Currently environment and project settings do not require periodic re-authentication,
    // though this is likely to change (see https://github.com/posthog/posthog/pull/22421).
    // In the meantime, we don't want a needless re-authentication modal:
    const AuthenticationAreaComponent =
        selectedLevel !== 'environment' && selectedLevel !== 'project'
            ? TimeSensitiveAuthenticationArea
            : React.Fragment

    const isSettingsScene = props.logicKey === 'settingsScene'

    const options: SettingOption[] = props.sectionId
        ? settings.map((s) => ({
              key: s.id,
              content: (
                  <OptionButton
                      to={urls.settings(selectedLevel, s.id)}
                      active={selectedSettingId === s.id}
                      isSettingsScene={isSettingsScene}
                      onClick={() => selectSetting(s.id)}
                  >
                      {s.title}
                  </OptionButton>
              ),
          }))
        : levels.map((level) => ({
              key: level,
              content: (
                  <OptionButton
                      to={urls.settings(level)}
                      isSettingsScene={isSettingsScene}
                      active={selectedLevel === level && !selectedSectionId}
                      onClick={() => selectLevel(level)}
                  >
                      <span className="text-muted-alt">{capitalizeFirstLetter(level)}</span>
                  </OptionButton>
              ),
              items: sections
                  .filter((x) => x.level === level)
                  .map((section) => ({
                      key: section.id,
                      content: (
                          <OptionButton
                              to={urls.settings(section.id)}
                              isSettingsScene={isSettingsScene}
                              active={selectedSectionId === section.id}
                              onClick={() => selectSection(section.id, level)}
                          >
                              {section.title}
                          </OptionButton>
                      ),
                  })),
          }))

    return (
        <div className={clsx('Settings flex', isCompact && 'Settings--compact')} ref={ref}>
            {hideSections ? null : (
                <>
                    {showOptions ? (
                        <div className="Settings__sections">
                            <OptionGroup options={options} />
                        </div>
                    ) : (
                        <LemonButton fullWidth sideIcon={<IconChevronRight />} onClick={() => openCompactNavigation()}>
                            {capitalizeFirstLetter(selectedLevel)}
                            {selectedSection ? ` / ${selectedSection.title}` : null}
                        </LemonButton>
                    )}
                    {isCompact ? <LemonDivider /> : null}
                </>
            )}

            <AuthenticationAreaComponent>
                <div className="flex-1 w-full space-y-2 min-w-0">
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

                    <SettingsRenderer {...props} />
                </div>
            </AuthenticationAreaComponent>
        </div>
    )
}

function SettingsRenderer(props: SettingsLogicProps): JSX.Element {
    const { settings, selectedLevel, selectedSectionId } = useValues(settingsLogic(props))
    const { selectSetting } = useActions(settingsLogic(props))

    return (
        <div className="space-y-8">
            {settings.length ? (
                settings.map((x) => (
                    <div key={x.id} className="relative">
                        <h2 id={x.id} className="flex gap-2 items-center">
                            {x.title}
                            <LemonButton
                                icon={<IconLink />}
                                size="small"
                                to={urls.settings(selectedSectionId ?? selectedLevel, x.id)}
                                onClick={
                                    // Outside of /settings, we want to select the level without navigating
                                    props.logicKey === 'settingsScene'
                                        ? (e) => {
                                              selectSetting(x.id)
                                              e.preventDefault()
                                          }
                                        : undefined
                                }
                            />
                        </h2>
                        {x.description && <p>{x.description}</p>}

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
        <ul className="space-y-px">
            {options.map((option) => (
                <>
                    <li key={option.key} className={depthMap[depth]}>
                        {option.content}
                    </li>
                    {option.items ? <OptionGroup options={option.items} depth={depth + 1} /> : null}
                </>
            ))}
        </ul>
    )
}

const OptionButton = ({
    to,
    active,
    onClick,
    children,
    isSettingsScene,
}: Pick<LemonButtonProps, 'to' | 'children' | 'active'> & {
    isSettingsScene: boolean
    onClick: () => void
}): JSX.Element => {
    return (
        <LemonButton
            to={to}
            onClick={
                isSettingsScene
                    ? (e) => {
                          onClick()
                          e.preventDefault()
                      }
                    : undefined
            }
            size="small"
            fullWidth
            active={active}
        >
            {children}
        </LemonButton>
    )
}
