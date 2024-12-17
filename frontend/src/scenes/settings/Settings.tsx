import './Settings.scss'

import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'
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

export function Settings({
    hideSections = false,
    ...props
}: SettingsLogicProps & { hideSections?: boolean }): JSX.Element {
    const { selectedSectionId, selectedSection, selectedLevel, sections, isCompactNavigationOpen, levels } = useValues(
        settingsLogic(props)
    )
    const { selectSection, selectLevel, openCompactNavigation } = useActions(settingsLogic(props))
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

    const showSections = isCompact ? isCompactNavigationOpen : true

    // Currently environment and project settings do not require periodic re-authentication,
    // though this is likely to change (see https://github.com/posthog/posthog/pull/22421).
    // In the meantime, we don't want a needless re-authentication modal:
    const AuthenticationAreaComponent =
        selectedLevel !== 'environment' && selectedLevel !== 'project'
            ? TimeSensitiveAuthenticationArea
            : React.Fragment

    return (
        <div className={clsx('Settings flex', isCompact && 'Settings--compact')} ref={ref}>
            {hideSections ? null : (
                <>
                    {showSections ? (
                        <div className="Settings__sections">
                            <ul className="space-y-px">
                                {levels.map((level) => (
                                    <li key={level} className="space-y-px">
                                        <LemonButton
                                            to={urls.settings(level)}
                                            onClick={
                                                // Outside of /settings, we want to select the level without navigating
                                                props.logicKey === 'settingsScene'
                                                    ? (e) => {
                                                          selectLevel(level)
                                                          e.preventDefault()
                                                      }
                                                    : undefined
                                            }
                                            size="small"
                                            fullWidth
                                            active={selectedLevel === level && !selectedSectionId}
                                        >
                                            <span className="text-[var(--content-tertiary)]">
                                                {capitalizeFirstLetter(level)}
                                            </span>
                                        </LemonButton>

                                        <ul className="space-y-px">
                                            {sections
                                                .filter((x) => x.level === level)
                                                .map((section) => (
                                                    <li key={section.id} className="pl-4">
                                                        <LemonButton
                                                            to={urls.settings(section.id)}
                                                            onClick={
                                                                // Outside of /settings, we want to select the level without navigating
                                                                props.logicKey === 'settingsScene'
                                                                    ? (e) => {
                                                                          selectSection(section.id, section.level)
                                                                          e.preventDefault()
                                                                      }
                                                                    : undefined
                                                            }
                                                            size="small"
                                                            fullWidth
                                                            active={selectedSectionId === section.id}
                                                        >
                                                            {section.title}
                                                        </LemonButton>
                                                    </li>
                                                ))}
                                        </ul>
                                    </li>
                                ))}
                            </ul>
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
