import './Toolbar.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PostHog } from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import {
    IconBolt,
    IconCamera,
    IconCheck,
    IconCursorClick,
    IconDay,
    IconEye,
    IconFlask,
    IconGear,
    IconHide,
    IconLeave,
    IconLive,
    IconMessage,
    IconNight,
    IconPieChart,
    IconQuestion,
    IconSearch,
    IconSpotlight,
    IconStethoscope,
    IconToggle,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonBadge, Spinner } from '@posthog/lemon-ui'

import { AnimatedLogomark } from 'lib/brand/Logomark'
import { FeatureFlagKey } from 'lib/constants'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconFlare, IconMenu } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { Link } from 'lib/lemon-ui/Link'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { AuthConfirmModal } from '~/toolbar/bar/AuthConfirmModal'
import { PII_MASKING_PRESET_COLORS } from '~/toolbar/bar/piiMaskingStyles'
import { ToolbarFeatureId, toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { UiHostConfigModal } from '~/toolbar/bar/UiHostConfigModal'
import { EventDebugMenu } from '~/toolbar/debug/EventDebugMenu'
import { ExperimentsToolbarMenu } from '~/toolbar/experiments/ExperimentsToolbarMenu'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { productToursLogic } from '~/toolbar/product-tours/productToursLogic'
import { ProductToursSidebar } from '~/toolbar/product-tours/ProductToursSidebar'
import { ProductToursToolbarMenu } from '~/toolbar/product-tours/ProductToursToolbarMenu'
import { screenshotUploadLogic } from '~/toolbar/screenshot-upload/screenshotUploadLogic'
import { ScreenshotUploadModal } from '~/toolbar/screenshot-upload/ScreenshotUploadModal'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { SurveySidebar } from '~/toolbar/surveys/SurveySidebar'
import { surveysToolbarLogic } from '~/toolbar/surveys/surveysToolbarLogic'
import { SurveysToolbarMenu } from '~/toolbar/surveys/SurveysToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { useToolbarFeatureFlag } from '~/toolbar/toolbarPosthogJS'
import { WebVitalsToolbarMenu } from '~/toolbar/web-vitals/WebVitalsToolbarMenu'

import { ToolbarButton } from './ToolbarButton'

const HELP_URL = 'https://posthog.com/docs/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

type ToolbarFeatureConfig = {
    id: ToolbarFeatureId
    label: string
    icon: JSX.Element
    flag?: FeatureFlagKey
}

const TOOLBAR_FEATURES: readonly ToolbarFeatureConfig[] = [
    { id: 'inspect', label: 'Inspect element', icon: <IconSearch /> },
    { id: 'heatmap', label: 'Heatmaps', icon: <IconCursorClick /> },
    { id: 'actions', label: 'Actions', icon: <IconBolt /> },
    { id: 'flags', label: 'Feature flags', icon: <IconToggle /> },
    { id: 'debugger', label: 'Event debugger', icon: <IconLive /> },
    { id: 'web-vitals', label: 'Web vitals', icon: <IconPieChart /> },
    { id: 'experiments', label: 'Experiments', icon: <IconFlask /> },
    { id: 'product-tours', label: 'Product tours', icon: <IconSpotlight />, flag: 'product-tours-2025' },
    { id: 'surveys', label: 'Surveys', icon: <IconMessage />, flag: 'surveys-toolbar' },
]

function useAvailableToolbarFeatures(): Set<ToolbarFeatureId> {
    const productToursFlag = useToolbarFeatureFlag('product-tours-2025')
    const surveysFlag = useToolbarFeatureFlag('surveys-toolbar')
    const inStory = inStorybook() || inStorybookTestRunner()

    const available = new Set<ToolbarFeatureId>()
    for (const feature of TOOLBAR_FEATURES) {
        if (!feature.flag) {
            available.add(feature.id)
            continue
        }
        if (feature.flag === 'product-tours-2025' && (inStory || productToursFlag)) {
            available.add(feature.id)
        } else if (feature.flag === 'surveys-toolbar' && surveysFlag) {
            available.add(feature.id)
        }
    }
    return available
}

function EnabledStatusItem({ label, value }: { label: string; value: boolean }): JSX.Element {
    return (
        <div className="flex justify-between items-center w-full">
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
                    <div className="flex justify-between items-center w-full">
                        <div>version: </div>
                        <div>{posthog?.version || 'posthog not available'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
                        <div>api host: </div>
                        <div>{posthog?.config.api_host}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex justify-between items-center w-full">
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
                    <div className="flex justify-between items-center w-full">
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
                    <div className="flex justify-between items-center w-full">
                        <div>session recording status: </div>
                        <div>{posthog?.sessionRecording?.status || 'unknown'}</div>
                    </div>
                ),
            },
            {
                label: (
                    <div className="flex items-center w-full">
                        <Link to={posthog?.get_session_replay_url()} target="_blank">
                            View current session recording
                        </Link>
                    </div>
                ),
            },
        ],
    }
}

function customizeToolbarMenuItem(
    availableFeatures: Set<ToolbarFeatureId>,
    disabledFeatures: ToolbarFeatureId[],
    setFeatureEnabled: (featureId: ToolbarFeatureId, enabled: boolean) => void
): LemonMenuItem {
    const items: LemonMenuItem[] = TOOLBAR_FEATURES.filter((feature) => availableFeatures.has(feature.id)).map(
        (feature) => {
            const isEnabled = !disabledFeatures.includes(feature.id)
            const enabledCount = TOOLBAR_FEATURES.filter(
                (f) => availableFeatures.has(f.id) && !disabledFeatures.includes(f.id)
            ).length
            const wouldDisableLast = isEnabled && enabledCount <= 1
            return {
                icon: feature.icon,
                label: feature.label,
                sideIcon: isEnabled ? <IconCheck /> : <IconX className="text-muted" />,
                active: isEnabled,
                disabledReason: wouldDisableLast ? 'At least one feature must be enabled' : undefined,
                onClick: () => setFeatureEnabled(feature.id, !isEnabled),
            }
        }
    )

    return {
        icon: <IconGear />,
        label: 'Customize toolbar',
        placement: 'right',
        custom: true,
        items,
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
    const {
        hedgehogModeEnabled,
        hedgehogModeAvailable,
        theme,
        posthog,
        piiMaskingEnabled,
        piiMaskingColor,
        piiWarning,
        disabledFeatures,
    } = useValues(toolbarLogic)
    const {
        setHedgehogModeEnabled,
        toggleTheme,
        togglePiiMasking,
        setPiiMaskingColor,
        startGracefulExit,
        openHedgehogOptions,
        setFeatureEnabled,
    } = useActions(toolbarLogic)
    const availableFeatures = useAvailableToolbarFeatures()
    const { isAuthenticated } = useValues(toolbarConfigLogic)
    const { logout } = useActions(toolbarConfigLogic)
    const { isTakingScreenshot } = useValues(screenshotUploadLogic)
    const { takeScreenshot } = useActions(screenshotUploadLogic)

    const [loadingSurveys, setLoadingSurveys] = useState(true)
    const [surveysCount, setSurveysCount] = useState(0)

    useEffect(() => {
        posthog?.surveys?.getSurveys((surveys: any[]) => {
            setSurveysCount(surveys.length)
            setLoadingSurveys(false)
        }, false)
    }, [posthog])

    const showScreenshotForEvent = useToolbarFeatureFlag('event-media-previews')

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    return (
        <>
            <ScreenshotUploadModal />
            <LemonMenu
                placement="top-end"
                fallbackPlacements={['bottom-end']}
                items={
                    [
                        {
                            icon: <>🦔</>,
                            label: hedgehogModeEnabled ? 'Disable hedgehog mode' : 'Hedgehog mode',
                            disabledReason: !hedgehogModeAvailable
                                ? "Hedgehog mode is disabled. Hedgehog mode uses `new Function` directives to render WebGL, and that requires 'unsafe-eval' in your Content Security Policy's script-src directive"
                                : undefined,
                            onClick: () => {
                                setHedgehogModeEnabled(!hedgehogModeEnabled)
                            },
                        },
                        hedgehogModeEnabled && hedgehogModeAvailable
                            ? {
                                  icon: <IconFlare />,
                                  label: 'Hedgehog options',
                                  onClick: () => {
                                      openHedgehogOptions()
                                  },
                              }
                            : undefined,
                        {
                            icon: currentlyLightMode ? <IconNight /> : <IconDay />,
                            label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                            onClick: () => toggleTheme(),
                        },
                        showScreenshotForEvent
                            ? {
                                  icon: <IconCamera />,
                                  label: 'Screenshot for event',
                                  onClick: takeScreenshot,
                                  disabled: isTakingScreenshot,
                              }
                            : undefined,
                        ...piiMaskingMenuItem(
                            piiMaskingEnabled,
                            piiMaskingColor,
                            togglePiiMasking,
                            setPiiMaskingColor,
                            piiWarning
                        ),
                        customizeToolbarMenuItem(availableFeatures, disabledFeatures, setFeatureEnabled),
                        postHogDebugInfoMenuItem(posthog, loadingSurveys, surveysCount),
                        {
                            icon: <IconQuestion />,
                            label: 'Help',
                            onClick: () => {
                                window.open(HELP_URL, '_blank')?.focus()
                            },
                        },
                        isAuthenticated ? { icon: <IconLeave />, label: 'Sign out', onClick: logout } : undefined,
                        { icon: <IconX />, label: 'Close toolbar', onClick: startGracefulExit },
                    ].filter(Boolean) as LemonMenuItems
                }
                maxContentWidth={true}
            >
                <ToolbarButton>{isTakingScreenshot ? <Spinner /> : <IconMenu />}</ToolbarButton>
            </LemonMenu>
        </>
    )
}

export function ToolbarInfoMenu(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized, isBlurred } = useValues(toolbarLogic)
    const { setMenu } = useActions(toolbarLogic)

    const { isAuthenticated } = useValues(toolbarConfigLogic)

    const productToursFlag = useToolbarFeatureFlag('product-tours-2025')
    const showProductTours = inStorybook() || inStorybookTestRunner() || productToursFlag

    const surveysFlag = useToolbarFeatureFlag('surveys-toolbar')
    const showSurveys = surveysFlag

    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : visibleMenu === 'debugger' ? (
        <EventDebugMenu />
    ) : visibleMenu === 'web-vitals' ? (
        <WebVitalsToolbarMenu />
    ) : visibleMenu === 'experiments' ? (
        <ExperimentsToolbarMenu />
    ) : visibleMenu === 'product-tours' && showProductTours ? (
        <ProductToursToolbarMenu />
    ) : visibleMenu === 'surveys' && showSurveys ? (
        <SurveysToolbarMenu />
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
    const { minimized, position, isDragging, hedgehogMode, isEmbeddedInApp, isExiting, isLoading, disabledFeatures } =
        useValues(toolbarLogic)
    const { setVisibleMenu, toggleMinimized, onMouseOrTouchDown, setElement, setIsBlurred, completeGracefulExit } =
        useActions(toolbarLogic)
    const { isAuthenticated, userIntent, authStatus, uiHostConfigModalVisible, authConfirmModalVisible } =
        useValues(toolbarConfigLogic)
    const { authenticate, openUiHostConfigModal, closeUiHostConfigModal, closeAuthConfirmModal } =
        useActions(toolbarConfigLogic)
    const { selectedTourId, isPreviewing } = useValues(productToursLogic)
    const { isCreating: isSurveyCreating } = useValues(surveysToolbarLogic)

    const availableFeatures = useAvailableToolbarFeatures()
    const isFeatureVisible = (id: ToolbarFeatureId): boolean =>
        availableFeatures.has(id) && !disabledFeatures.includes(id)
    const showProductTours = isFeatureVisible('product-tours')
    const showSurveys = isFeatureVisible('surveys')

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

        if (userIntent === 'add-product-tour' || userIntent === 'edit-product-tour') {
            setVisibleMenu('product-tours')
        }
    }, [userIntent]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (isEmbeddedInApp) {
        return null
    }

    const showToursSidebar = selectedTourId !== null && !isPreviewing

    const visibleFeatureCount = TOOLBAR_FEATURES.filter((f) => isFeatureVisible(f.id)).length

    return (
        <>
            {showToursSidebar && <ProductToursSidebar />}
            {isSurveyCreating && <SurveySidebar />}
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx('Toolbar', {
                    'Toolbar--minimized': minimized,
                    'Toolbar--hedgehog-mode': hedgehogMode,
                    'Toolbar--dragging': isDragging,
                })}
                onMouseDown={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onTouchStart={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onMouseOver={() => setIsBlurred(false)}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--toolbar-button-x': `${position.x}px`,
                        '--toolbar-button-y': `${position.y}px`,
                        '--toolbar-feature-count': visibleFeatureCount,
                    } as any
                }
            >
                <ToolbarButton
                    onClick={isAuthenticated ? toggleMinimized : authenticate}
                    title={isAuthenticated ? 'Minimize' : 'Authenticate the PostHog Toolbar'}
                    titleMinimized={isAuthenticated ? 'Expand the toolbar' : 'Authenticate the PostHog Toolbar'}
                >
                    <AnimatedLogomark
                        animate={isLoading || authStatus === 'checking' || authStatus === 'authenticating'}
                        animateOnce={isExiting ? completeGracefulExit : undefined}
                        className="Toolbar__logomark"
                    />
                </ToolbarButton>
                {isAuthenticated ? (
                    <>
                        {isFeatureVisible('inspect') && (
                            <ToolbarButton menuId="inspect">
                                <IconSearch />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('heatmap') && (
                            <ToolbarButton menuId="heatmap">
                                <IconCursorClick />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('actions') && (
                            <ToolbarButton menuId="actions">
                                <IconBolt />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('flags') && (
                            <ToolbarButton menuId="flags" title="Feature flags">
                                <IconToggle />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('debugger') && (
                            <ToolbarButton menuId="debugger" title="Event debugger">
                                <IconLive />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('web-vitals') && (
                            <ToolbarButton menuId="web-vitals" title="Web vitals">
                                <IconPieChart />
                            </ToolbarButton>
                        )}
                        {isFeatureVisible('experiments') && (
                            <ToolbarButton menuId="experiments" title="Experiments">
                                <IconFlask />
                            </ToolbarButton>
                        )}
                        {showProductTours && (
                            <ToolbarButton menuId="product-tours" title="Product tours">
                                <IconSpotlight />
                            </ToolbarButton>
                        )}
                        {showSurveys && (
                            <ToolbarButton menuId="surveys" title="Surveys">
                                <IconMessage />
                            </ToolbarButton>
                        )}
                    </>
                ) : authStatus === 'checking' || authStatus === 'authenticating' ? (
                    <ToolbarButton flex>
                        <span className="flex items-center gap-1">
                            <Spinner /> {authStatus === 'authenticating' ? 'Authenticating…' : 'Checking…'}
                        </span>
                    </ToolbarButton>
                ) : authStatus === 'error' ? (
                    <ToolbarButton
                        flex
                        onClick={openUiHostConfigModal}
                        title="PostHog app unreachable — click for help"
                    >
                        <span className="flex items-center gap-1">
                            Authenticate <IconWarning className="text-warning" />
                        </span>
                    </ToolbarButton>
                ) : (
                    <ToolbarButton flex onClick={authenticate}>
                        Authenticate
                    </ToolbarButton>
                )}
                <UiHostConfigModal visible={uiHostConfigModalVisible} onClose={closeUiHostConfigModal} />
                <AuthConfirmModal visible={authConfirmModalVisible} onClose={closeAuthConfirmModal} />

                <MoreMenu />
            </div>
        </>
    )
}
