import './Toolbar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PostHog } from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import {
    IconBolt,
    IconCheck,
    IconCursorClick,
    IconDay,
    IconEye,
    IconHide,
    IconLive,
    IconLogomark,
    IconNight,
    IconPieChart,
    IconQuestion,
    IconSearch,
    IconStethoscope,
    IconTestTube,
    IconToggle,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonBadge, Spinner } from '@posthog/lemon-ui'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { IconFlare, IconMenu } from 'lib/lemon-ui/icons'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { PII_MASKING_PRESET_COLORS } from '~/toolbar/bar/piiMaskingStyles'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { EventDebugMenu } from '~/toolbar/debug/EventDebugMenu'
import { ExperimentsToolbarMenu } from '~/toolbar/experiments/ExperimentsToolbarMenu'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { useToolbarFeatureFlag } from '~/toolbar/toolbarPosthogJS'
import { WebVitalsToolbarMenu } from '~/toolbar/web-vitals/WebVitalsToolbarMenu'

import { HedgehogMenu } from '../hedgehog/HedgehogMenu'
import { ToolbarButton } from './ToolbarButton'

const HELP_URL = 'https://posthog.com/docs/user-guides/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

function EnabledStatusItem({ label, value }: { label: string; value: boolean }): JSX.Element {
    return (
        <div className="flex w-full justify-between items-center">
            <div>{label}: </div>
            <div>{value ? <IconCheck /> : <IconX />}</div>
        </div>
    )
}

function postHogDebugInfoMenuItem(
    posthog: PostHog | null,
    loadingSurveys: boolean,
    surveysCount: number
): LemonMenuItem {
    const isAutocaptureEnabled = posthog?.autocapture?.isEnabled

    return {
        icon: <IconStethoscope />,
        label: 'Debug info',
        items: [
            {
                label: (
                    <div className="flex w-full justify-between items-center">
                        <div>version: </div>
                        <div>{posthog?.version || 'posthog not available'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex w-full justify-between items-center">
                        <div>api host: </div>
                        <div>{posthog?.config.api_host}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex w-full justify-between items-center">
                        <div>ui host: </div>
                        <div>{posthog?.config.ui_host || 'not set'}</div>
                    </div>
                ),
            },
            { label: <EnabledStatusItem label="autocapture" value={!!isAutocaptureEnabled} /> },
            {
                label: (
                    <EnabledStatusItem
                        label="rageclicks"
                        value={!!(isAutocaptureEnabled && posthog?.config.rageclick)}
                    />
                ),
            },
            {
                label: (
                    <EnabledStatusItem
                        label="dead clicks"
                        value={!!posthog?.deadClicksAutocapture?.lazyLoadedDeadClicksAutocapture}
                    />
                ),
            },
            { label: <EnabledStatusItem label="heatmaps" value={!!posthog?.heatmaps?.isEnabled} /> },
            {
                label: (
                    <div className="flex w-full justify-between items-center">
                        <div>surveys: </div>
                        <div>
                            {loadingSurveys ? <Spinner /> : <LemonBadge.Number showZero={true} count={surveysCount} />}
                        </div>
                    </div>
                ),
            },
            { label: <EnabledStatusItem label="session recording" value={!!posthog?.sessionRecording?.started} /> },
            {
                label: (
                    <div className="flex w-full justify-between items-center">
                        <div>session recording status: </div>
                        <div>{posthog?.sessionRecording?.status || 'unknown'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex w-full items-center">
                        <Link to={posthog?.get_session_replay_url()} target="_blank">
                            View current session recording
                        </Link>
                    </div>
                ),
            },
        ],
    }
}

function piiMaskingMenuItem(
    piiMaskingEnabled: boolean,
    piiMaskingColor: string,
    togglePiiMasking: () => void,
    setPiiMaskingColor: (color: string) => void,
    piiWarning: string[] | null
): LemonMenuItem[] {
    return [
        {
            icon: piiMaskingEnabled ? <IconEye /> : <IconHide />,
            label: piiMaskingEnabled ? 'Show PII' : 'Hide PII',
            sideIcon: piiWarning && piiWarning.length > 0 ? <IconWarning className="text-warning" /> : undefined,
            tooltip: piiWarning && piiWarning.length > 0 ? piiWarning.join('\n') : undefined,
            onClick: (e: React.MouseEvent) => {
                e.preventDefault()
                e.stopPropagation()
                togglePiiMasking()
            },
            custom: true,
        },
        piiMaskingEnabled
            ? {
                  icon: (
                      <div
                          className="w-4 h-4 rounded border"
                          // eslint-disable-next-line react/forbid-dom-props
                          style={{ backgroundColor: piiMaskingColor }}
                      />
                  ),
                  label: 'PII masking color',
                  placement: 'right',
                  disabled: !piiMaskingEnabled,
                  items: PII_MASKING_PRESET_COLORS.map((preset) => ({
                      icon: (
                          <div
                              className="w-4 h-4 rounded border"
                              // eslint-disable-next-line react/forbid-dom-props
                              style={{ backgroundColor: preset.value }}
                          />
                      ),
                      label: preset.label,
                      onClick: () => {
                          setPiiMaskingColor(preset.value)
                      },
                      active: piiMaskingColor === preset.value,
                      custom: true,
                  })),
              }
            : undefined,
    ].filter(Boolean) as LemonMenuItem[]
}

function MoreMenu(): JSX.Element {
    const { hedgehogMode, theme, posthog, piiMaskingEnabled, piiMaskingColor, piiWarning } = useValues(toolbarLogic)
    const { setHedgehogMode, toggleTheme, setVisibleMenu, togglePiiMasking, setPiiMaskingColor } =
        useActions(toolbarLogic)

    const [loadingSurveys, setLoadingSurveys] = useState(true)
    const [surveysCount, setSurveysCount] = useState(0)

    useEffect(() => {
        posthog?.surveys?.getSurveys((surveys: any[]) => {
            setSurveysCount(surveys.length)
            setLoadingSurveys(false)
        }, false)
    }, [posthog])

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    const { logout } = useActions(toolbarConfigLogic)

    return (
        <LemonMenu
            placement="top-end"
            fallbackPlacements={['bottom-end']}
            items={
                [
                    {
                        icon: <>🦔</>,
                        label: hedgehogMode ? 'Disable hedgehog mode' : 'Hedgehog mode',
                        onClick: () => {
                            setHedgehogMode(!hedgehogMode)
                        },
                    },
                    hedgehogMode
                        ? {
                              icon: <IconFlare />,
                              label: 'Hedgehog options',
                              onClick: () => {
                                  setVisibleMenu('hedgehog')
                              },
                          }
                        : undefined,
                    {
                        icon: currentlyLightMode ? <IconNight /> : <IconDay />,
                        label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                        onClick: () => toggleTheme(),
                    },
                    ...piiMaskingMenuItem(
                        piiMaskingEnabled,
                        piiMaskingColor,
                        togglePiiMasking,
                        setPiiMaskingColor,
                        piiWarning
                    ),
                    postHogDebugInfoMenuItem(posthog, loadingSurveys, surveysCount),
                    {
                        icon: <IconQuestion />,
                        label: 'Help',
                        onClick: () => {
                            window.open(HELP_URL, '_blank')?.focus()
                        },
                    },
                    { icon: <IconX />, label: 'Close toolbar', onClick: logout },
                ].filter(Boolean) as LemonMenuItems
            }
            maxContentWidth={true}
        >
            <ToolbarButton>
                <IconMenu />
            </ToolbarButton>
        </LemonMenu>
    )
}

export function ToolbarInfoMenu(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized, isBlurred } = useValues(toolbarLogic)
    const { setMenu } = useActions(toolbarLogic)

    const { isAuthenticated } = useValues(toolbarConfigLogic)

    const showExperimentsFlag = useToolbarFeatureFlag('web-experiments')
    const showExperiments = inStorybook() || inStorybookTestRunner() || showExperimentsFlag

    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : visibleMenu === 'hedgehog' ? (
        <HedgehogMenu />
    ) : visibleMenu === 'debugger' ? (
        <EventDebugMenu />
    ) : visibleMenu === 'web-vitals' ? (
        <WebVitalsToolbarMenu />
    ) : visibleMenu === 'experiments' && showExperiments ? (
        <ExperimentsToolbarMenu />
    ) : null

    useEffect(() => {
        setMenu(ref.current)
        return () => setMenu(null)
    }, [ref.current]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!isAuthenticated) {
        return null
    }

    return (
        <div
            className={clsx(
                'ToolbarMenu',
                !!content && 'ToolbarMenu--visible',
                isDragging && 'ToolbarMenu--dragging',
                isBlurred && 'ToolbarMenu--blurred',
                menuProperties.isBelow && 'ToolbarMenu--below'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: menuProperties.transform,
            }}
        >
            <div
                ref={ref}
                className="ToolbarMenu__content"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    maxHeight: menuProperties.maxHeight,
                }}
            >
                {content}
            </div>
        </div>
    )
}

export function Toolbar(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimized, position, isDragging, hedgehogMode, isEmbeddedInApp } = useValues(toolbarLogic)
    const { setVisibleMenu, toggleMinimized, onMouseOrTouchDown, setElement, setIsBlurred } = useActions(toolbarLogic)
    const { isAuthenticated, userIntent } = useValues(toolbarConfigLogic)
    const { authenticate } = useActions(toolbarConfigLogic)

    const showExperimentsFlag = useToolbarFeatureFlag('web-experiments')
    const showExperiments = inStorybook() || inStorybookTestRunner() || showExperimentsFlag

    useEffect(() => {
        setElement(ref.current)
        return () => setElement(null)
    }, [ref.current]) // oxlint-disable-line react-hooks/exhaustive-deps

    useKeyboardHotkeys(
        {
            escape: { action: () => setVisibleMenu('none'), willHandleEvent: true },
        },
        []
    )

    useEffect(() => {
        if (userIntent === 'add-action' || userIntent === 'edit-action') {
            setVisibleMenu('actions')
        }

        if (userIntent === 'add-experiment' || userIntent === 'edit-experiment') {
            setVisibleMenu('experiments')
        }

        if (userIntent === 'heatmaps') {
            setVisibleMenu('heatmap')
        }
    }, [userIntent]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (isEmbeddedInApp) {
        return null
    }

    return (
        <>
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx('Toolbar', {
                    'Toolbar--minimized': minimized,
                    'Toolbar--hedgehog-mode': hedgehogMode,
                    'Toolbar--dragging': isDragging,
                    'Toolbar--with-experiments': showExperiments,
                })}
                onMouseDown={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onTouchStart={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onMouseOver={() => setIsBlurred(false)}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--toolbar-button-x': `${position.x}px`,
                        '--toolbar-button-y': `${position.y}px`,
                    } as any
                }
            >
                <ToolbarButton
                    onClick={isAuthenticated ? toggleMinimized : authenticate}
                    title={isAuthenticated ? 'Minimize' : 'Authenticate the PostHog Toolbar'}
                    titleMinimized={isAuthenticated ? 'Expand the toolbar' : 'Authenticate the PostHog Toolbar'}
                >
                    <IconLogomark />
                </ToolbarButton>
                {isAuthenticated ? (
                    <>
                        <ToolbarButton menuId="inspect">
                            <IconSearch />
                        </ToolbarButton>
                        <ToolbarButton menuId="heatmap">
                            <IconCursorClick />
                        </ToolbarButton>
                        <ToolbarButton menuId="actions">
                            <IconBolt />
                        </ToolbarButton>
                        <ToolbarButton menuId="flags" title="Feature flags">
                            <IconToggle />
                        </ToolbarButton>
                        <ToolbarButton menuId="debugger" title="Event debugger">
                            <IconLive />
                        </ToolbarButton>
                        <ToolbarButton menuId="web-vitals" title="Web vitals">
                            <IconPieChart />
                        </ToolbarButton>
                        {showExperiments && (
                            <ToolbarButton menuId="experiments" title="Experiments">
                                <IconTestTube />
                            </ToolbarButton>
                        )}
                    </>
                ) : (
                    <ToolbarButton flex onClick={authenticate}>
                        Authenticate
                    </ToolbarButton>
                )}

                <MoreMenu />
            </div>
        </>
    )
}
